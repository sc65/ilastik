import SocketServer
import threading
import socket
import logging
import string
import json

logger = logging.getLogger(__name__)

class TCPServerBoundToShell(SocketServer.TCPServer):
    def __init__(self, server_address, RequestHandlerClass, shell=None, bind_and_activate=True):
        self.shell = shell
        SocketServer.TCPServer.__init__(self, server_address, RequestHandlerClass)

class MessageServer(object):
    connections = {}
    
    def __init__(self, parent, host, port, startListening=True):
        self.parent = parent
        self.host = host
        self.port = port   
        
        if startListening:
            self.setupServer()
            self.startListening()
    
    def __del__(self):
        self.closeConnections()
        self.thread.__stop()
    
    def setupServer(self):
        self.server = TCPServerBoundToShell((self.host, self.port), TCPRequestHandler, shell=self.parent)
        self.thread = threading.Thread(name="IlastikTCPServer", target=self.server.serve_forever)
        
    def startListening(self): 
        try:
            if not self.server is None:
                self.thread.start()
            else:
                raise Exception('TCP Server not set up yet')
        except:
            # not listening
            pass

    def connect(self, host, port, name):
        try:
            self.connections[name] = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.connections[name].connect((host, port))
        except Exception, e:
            logger.error("Error connecting to socket '%s': %s" % (name, e))
    
    def closeConnection(self, name):
        if name in self.connections:
            try:
                self.connections[name].close()
            except:
                pass
            del self.connections[name]
    
    def closeConnections(self):
        for name in self.connections:
            self.closeConnection(name)
    
    def send(self, name, data):  
        try:
            if name in self.connections:
                self.connections[name].send(json.dumps(data))
            else:
                raise Exception("No connection with name '%s' exists" % name)
        except Exception, e:
            logger.error("Error sending message '%s' to '%s': %s" % (data, name, e))

class TCPRequestHandler(SocketServer.StreamRequestHandler):                 
    def handle(self):
        data = json.loads(self.rfile.readline().strip())
        logger.info("%s wrote: %s" % (self.client_address[0], data))
        
        print data
        
        # keys to lowercase
        dict((k.lower(), v) for k,v in data.iteritems())
        
        if 'command' in data:
            if data['command'] == 'jump_to_position':
                pos5d = []
                for l in 'txyzc':
                    if l in data:
                        pos5d.append(data[l])
                    else:
                        pos5d.append(0)
                print "pos5d:", pos5d
                self.server.shell.setAllViewersPosition(pos5d)
                