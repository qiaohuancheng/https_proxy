import socket
import select
import threading
import queue
import traceback
import uuid
import pdb
import os
import time


BUFSIZE=8192
#socket的recv函数和connect函数会阻塞，这里设置超时时间
TIMEOUT=1

class Connection(object):
    def __init__(self,socket):
        self.cid=str(socket.getpeername())
        self.client_socket=socket
        self.client_socket.settimeout(TIMEOUT)
        self.server_socket=None
        self.client_fd=self.client_socket.fileno()
        self.uplink_queue=queue.Queue()
        self.downlink_queue=queue.Queue()
        self.lock_of_server_socket=threading.Lock()
        self.is_server_socket_ok=False
        self.lock_of_client_socket=threading.Lock()
        self.is_client_socket_ok=True
        self.last_active_time=int(time.time())
        
    
    def print_recv(self, tag, data):
        #print(self.cid + " -> recv from " + tag + " : " + str(len(data)))
        return

    def print_send(self, tag, data):
        #print(self.cid + " -> send to " + tag + " : " + str(len(data)))
        return
    
    def print_close(self, tag):
        #print(self.cid + " -> close connection by " + tag)
        return
    
    def print_bind(self):
        #print(self.cid + " -> bind " + str(self.client_socket) + " and " + str(self.server_socket))
        return

    def netstat(self, port):
        #output = os.popen('netstat | grep ' + str(port))
        #print(self.cid + " -> " + output.read())
        return

    def try_connect_server(self):
        is_connect=False
        self.lock_of_server_socket.acquire()
        try:
            if not self.is_server_socket_ok:
                self.server_socket=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
                self.server_socket.settimeout(TIMEOUT)
                self.server_socket.connect((str(self.server_host),int(self.server_port)))
                self.is_server_socket_ok=True
                self.server_fd=self.server_socket.fileno()
                self.print_bind()
                is_connect=True
        except Exception as e:
            print("Unreachable server_host : " + str(self.server_host))
            raise e
        finally:       
            self.lock_of_server_socket.release()
        return is_connect

    def recv_from_client(self):
        self.last_active_time=int(time.time())
        uplink_data=self.client_socket.recv(BUFSIZE)
        if len(uplink_data) == 0:
            #port=self.client_socket.getpeername()[1]
            #self.netstat(port)
            raise Exception("recv empty from client_socket")
        if uplink_data.startswith(b"GET http") or uplink_data.startswith(b"CONNECT") or uplink_data.startswith(b"POST http"):
            host,port=self.extract_peer_from_data(uplink_data)
            self.server_host=host
            self.server_port=port
        if uplink_data.startswith(b"CONNECT"):
            #客户端发送https请求前，先发送connect报文，因此代理收到connect报文应回复如下内容
            connect_response=b"HTTP/1.0 200 Connection Established\r\n\r\n"
            self.client_socket.send(connect_response)
        else:            
            self.print_recv("client", uplink_data)
            self.uplink_queue.put(uplink_data)
            #必须读完，否则该连接对应的事件状态不变，epoll检测不出来，就没有后续的读事件了
            print(self.cid + " -> read data size = " + str(len(uplink_data)))
            while len(uplink_data) == BUFSIZE:
                uplink_data=self.client_socket.recv(BUFSIZE)
                self.print_recv("client", uplink_data)
                self.uplink_queue.put(uplink_data)
                print(self.cid + " -> read data size = " + str(len(uplink_data)))

        
    def send_to_client(self):
        self.last_active_time=int(time.time())
        while not self.downlink_queue.empty():
            downlink_data=self.downlink_queue.get()
            self.print_send("client", downlink_data)
            self.client_socket.send(downlink_data)
            
    def recv_from_server(self):
        self.last_active_time=int(time.time())
        downlink_data=self.server_socket.recv(BUFSIZE)
        if len(downlink_data) == 0:
            #port=self.server_socket.getsockname()[1]
            #self.netstat(port)
            raise Exception("recv empty from server_socket")
        self.downlink_queue.put(downlink_data)
        self.print_recv("server", downlink_data)
        
    def send_to_server(self):
        self.last_active_time=int(time.time())
        while not self.uplink_queue.empty():
            uplink_data=self.uplink_queue.get()
            self.print_send("server", uplink_data)
            self.server_socket.send(uplink_data)
        
    def extract_peer_from_data(self,uplink_data):   
        #http
        index_of_host=uplink_data.find(b"Host:")
        if index_of_host>-1:
            index_of_n=uplink_data.find(b"\n",index_of_host)
            ##host:===5
            host=uplink_data[index_of_host+5:index_of_n]
        else:
            ###no host sample :'GET http://saxn.sina.com.cn/mfp/view?......
            host=uplink_data.split(b"/")[2]                      
        host=str(host.decode().strip("\r").lstrip())
        if len(host.split(":"))==2:
            port=host.split(":")[1]
            domain_name=host.split(":")[0].strip("")
        else:
            port=80
            domain_name=host.split(":")[0].strip("")
        return domain_name,port
    
    def close_client_socket(self):
        self.lock_of_client_socket.acquire()
        try:
            if self.is_client_socket_ok:
                self.print_close("client")
                self.client_socket.close()
                self.client_socket=None
                self.client_fd=None
                self.is_client_socket_ok=False
                self.downlink_queue.queue.clear()
        except Exception as e:
            traceback.print_exc()
        finally:
            self.lock_of_client_socket.release()
    
    def close_server_socket(self):
        self.lock_of_server_socket.acquire()
        try:
            if self.is_server_socket_ok:
                self.print_close("server")
                self.server_socket.close()
                self.server_socket=None
                self.server_fd=None
                self.is_server_socket_ok=False
                self.uplink_queue.queue.clear()
        except Exception as e:
            traceback.print_exc()
        finally:
            self.lock_of_server_socket.release()

class Client_Processor(object):
    def __init__(self, server_processor):
        self.server_processor=server_processor
        self.server_processor.set_client_processor(self)
        self.epoll=select.epoll()
        threading.Thread(target=self.process,args=()).start()
        #文件句柄到所对应对象的字典，格式为{句柄：对象}
        self.fd_to_connection={}
        
    def prepare_send(self, connection):
        self.epoll.modify(connection.client_fd, select.EPOLLOUT | select.EPOLLIN | select.EPOLLHUP)
        
    def register_connection(self, connection):
        print(connection.cid + " -> register epoll : " + str(connection.client_fd))
        self.fd_to_connection.update({connection.client_fd: connection})
        self.epoll.register(connection.client_fd, select.EPOLLIN | select.EPOLLHUP)
    
    def unregister_fd(self, client_fd):
        try:
            self.epoll.unregister(client_fd)
            connection=self.fd_to_connection[client_fd]
            print(connection.cid + " -> unregister epoll : " + str(connection.client_fd))
            connection.close_client_socket()
            connection.close_server_socket()
            del self.fd_to_connection[client_fd]
        except Exception as e:
            return
        
    def process(self):
        while True:
            #轮询注册的事件集合，返回值为[(文件句柄，对应的事件)，(...),....]
            events = self.epoll.poll()
            for client_fd, event in events:
                try:
                    #关闭事件
                    if event & select.EPOLLRDHUP:
                        print("process hup for " + str(client_fd))
                        self.unregister_fd(client_fd)
                    #可读事件
                    elif event & select.EPOLLIN:
                        print("process in for " + str(client_fd))
                        connection = self.fd_to_connection.get(client_fd)
                        connection.recv_from_client()
                        self.server_processor.prepare_send(connection)
                    #可写事件
                    elif event & select.EPOLLOUT:
                        #print("process out for " + str(client_fd))
                        connection = self.fd_to_connection.get(client_fd)
                        self.epoll.modify(client_fd, select.EPOLLIN | select.EPOLLHUP)
                        connection.send_to_client()
                except Exception as e:
                    if is_print_exc(e):
                        traceback.print_exc()
                    self.unregister_fd(client_fd)
                
class Server_Processor(object):
    def __init__(self):
        self.epoll = select.epoll()
        threading.Thread(target=self.process,args=()).start()
        self.fd_to_connection={}
        
    def set_client_processor(self, client_processor):
        self.client_processor=client_processor
        
    def prepare_send(self, connection):
        is_connect=connection.try_connect_server()
        if is_connect:
            self.fd_to_connection.update({connection.server_fd: connection})
            self.epoll.register(connection.server_fd, select.EPOLLOUT | select.EPOLLIN | select.EPOLLHUP)
        else: 
            self.epoll.modify(connection.server_fd, select.EPOLLOUT | select.EPOLLIN | select.EPOLLHUP)
    
    def unregister_fd(self, server_fd):
        try:
            self.epoll.unregister(server_fd)
            connection=self.fd_to_connection[server_fd]
            connection.close_server_socket()
            del self.fd_to_connection[server_fd]
        except Exception as e:
            return
        
    def process(self):
        while True:
            #轮询注册的事件集合，返回值为[(文件句柄，对应的事件)，(...),....]
            events = self.epoll.poll()
            for server_fd, event in events:
                try:
                    #关闭事件
                    if event & select.EPOLLHUP:
                        print("process hup for " + str(server_fd))
                        self.unregister_fd(server_fd)
                    #可读事件
                    elif event & select.EPOLLIN:
                        connection = self.fd_to_connection.get(server_fd)
                        connection.recv_from_server()
                        self.client_processor.prepare_send(connection)
                    #可写事件
                    elif event & select.EPOLLOUT:
                        connection = self.fd_to_connection.get(server_fd)
                        self.epoll.modify(server_fd, select.EPOLLIN | select.EPOLLHUP)
                        connection.send_to_server()
                except Exception as e:
                    if is_print_exc(e):
                        traceback.print_exc()
                    self.unregister_fd(server_fd)

class Connection_finalizer(object):
    def __init__(self, server_processor, client_processor):
        self.connections=[]
        self.server_processor=server_processor
        self.client_processor=client_processor
        threading.Timer(10, self.process).start()

    def register_connection(self, connection):
        self.connections.append(connection)

    def process(self):
        for i in range(len(self.connections)-1, -1, -1):
            connection=self.connections[i]
            if int(time.time()) - connection.last_active_time >= 30:
                #and not connection.is_server_socket_ok:
                self.client_processor.unregister_fd(connection.client_fd)
                self.connections.pop(i)
        print("connections = " + str(len(self.connections)))
        threading.Timer(3, self.process).start()  

def is_print_exc(exception):
    if str(exception).startswith('recv empty from'):
        return False
    if str(exception).startswith('[Errno 104] Connection reset by peer'):
        return False
    return True
        
def get_local_address():
    #创建socket实例
    skt = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    #连接8.8.8.8，8.8.8.8是google提供的公共dns服务器
    skt.connect(('8.8.8.8',80))
    #获得连接信息，是一个tuple （ip，port）
    socketIpPort = skt.getsockname()
    skt.close() 
    ip=socketIpPort[0]
    return ip
    
class Proxy_Server(object):
    def __init__(self,host,port):
        self.server_processor=Server_Processor()
        self.client_processor=Client_Processor(self.server_processor)
        self.connection_finalizer=Connection_finalizer(self.server_processor, self.client_processor)
        self.host=host
        self.port=port
        #创建socket对象
        self.server_socket=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        #设置IP地址复用
        self.server_socket.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        #绑定IP地址
        self.server_socket.bind((host,port))
        #监听，并设置最大连接数
        self.server_socket.listen(1024)
 
    def start(self):
        while True:
            try:
                socket,addr=self.server_socket.accept()
                #pdb.set_trace()
                connection=Connection(socket)
                self.connection_finalizer.register_connection(connection)
                self.client_processor.register_connection(connection)
            except Exception  as e:
                traceback.print_exc()
    
if  __name__=="__main__":
    svr=Proxy_Server(get_local_address(),8080)
    svr.start()
    
    
