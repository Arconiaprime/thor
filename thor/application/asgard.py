import logging, os, sys

from twisted.application import internet
from twisted.internet import defer, reactor
from thor.application import service
from thor.application.servers import tcp, unix, web

class Asgard(service.DaemonService):
    def __init__(self, processes=None, iface='127.0.0.1', port='21189'):
        # Run the init routines on the parent class
        # this sets up all of the Twisted logic needed
        # later on
        service.DaemonService.__init__(self, daemon=True)
        # Initiate the logger. This acts as the default logger for the 
        # application namesapce. Service level components will pass their log 
        # messages through this namespace
        self.logger = logging.getLogger('thor.application.Asgard')
        # We need to know how many processes to start as crawlers
        # this gets saved as a variable which gets run in startService
        from thor.common.utils import num_processes, NO_PROCESS_ERR
        if processes is None:
            # By default if we'r enot told, we will find out a default
            # number of processes based on the number of physical
            # CPU cores here            
            processes = num_processes()
        # There is a chanc ethat the installation of python does not support
        # multiprocessing. If it doesn't we raise an exception here and get
        # out of the application before spawning anything
        if processes == NO_PROCESS_ERR:
            raise Exception('Multiprocessing is not supported on this system')
        # Save the number of processes for later - see startService
        self.processes = processes   
        # Set the actual listening interface variables here so that they exist
        # within the class - The default values are set below
        self.iface = None
        self.port = None
        # Set the management listening interface here we just pass off
        # to the function instead of checking logic for it in the constructor
        self.setListeningInterface( iface=iface, port=port )
        # Hold references to the servers and child processes running under this 
        # serice. Asgard acts as a hub for all information in the server application.
        self.servers = {}
        self.nodes = {}

    def create_server(self, iface='0.0.0.0', port='21189', root=None, 
            socket=None, sslcert=None, sslkey=None, sslchain=None):
        # All of the application servers exist in this import from here
        # we can manipulate them to spawn their factories and then their
        # specific protocols
        if socket is not None:
            # This will create a UNIX socket at the location of 'socket' and
            # listen for incomming connections form this location
            _server = unix.UNIXServer( socket=socket )
        elif root is not None:
            # This tells us we are going to create a web server. The Web Server
            # will accept connections on the port/interface combo and return
            # web requests. The catch here is we want to support SSL and REGULAR
            # HTTP requests
            if sslcert is not None:
                # TODO Create a SSLWebServer socket
                return None
            else:
                # TODO Check if root directory exists
                # TODO WebServer Caching?
                _server = web.WebServer( iface=iface, port=port, root=root )
        else:
            # Create a standard TCP server that listens for incomming connections
            # on this interface/port combo. The receivers here will be instances
            # of the basic.LineReceiver class and respond to requests
            _server = tcp.TCPServer( iface=iface, port=port )
        # The server represents a service that we store within our multiservice
        # so we need to set the parent service reference
        #_server.setServiceParent(self)
        # We need to queue the reactor for the initialization code
        _server.addEventTrigger('before', 'startup', _server.initialize)
        # The initialization routine should call immeadietly resulting in that
        # code running first. After we initialize we can set the reactor to call
        # the startService and kick the system into gear
        reactor.callWhenRunning(_server.startService)
        # We maintain an internal list of servers that we are watching in a list
        # for shutdowns and such this list will be interated through and every
        # server will drop it's connections on a graceful shutdown
        self.registerServer(_server)
        # Return the server instance to whatever called it and continue on from
        # there.
        return _server

    def initialize(self):
        print 'initialize -> %s' % self.uid

    def registerServer(self, server):
        print '-> registerServer -> %s' % server.uid

        if server.uid in self.servers:
            raise KeyError('Server already exists')

        self.servers[server.uid] = server

        server.fireEventTrigger('registered')

    def removeServer(self, server):
        print '-> removeServer -> %s' % server.uid

        if server.uid not in self.servers:
            raise KeyError('Server not registered')

        del self.servers[server.uid]

        server.fireEventTrigger('unregistered')

        # This logic takes place in the event of the LAST server
        # shutting down AND we are beginning to shutdown the application
        if not self.servers:
            if self._shutdownHook:
                self._shutdownHook.callback(None)

    def setListeningInterface(self, iface=None, port=None):
        if iface is not None:
            self.iface = iface
        if port is not None:
            self.port = port
    
    def startupHook(self, startup):
        print 'Asgard startupHook called'

        try:
            _server = self.create_server()
        except Exception as e:
            import traceback
            traceback.print_exc()

        startup.callback(None)
        
    def shutdownHook(self, shutdown):
        print 'Asgard shutdownHook called'
        # Create the deferred object which this class will use to fire the service's
        # primary shutdown when all assets have been shutdown. For Asgard this includes
        # any services and nodes that might have been launched
        d = self._shutdownHook = defer.Deferred()
        # Loop through all the nodes. The list is indexed by the process id of
        # the node process. The 'node' object returned will link us to the
        # process manager that controls the node's IO connections
        # to the main application
        for pid, node in self.nodes.iteritems():
            pass
        
        for uid, server in self.servers.iteritems(): 
            server.addEventTrigger('after', 'shutdown', self.removeServer, server)          
            reactor.callFromThread(server.stopService)
        # Finally we chain the services deferred to our deferred here. When we have no more
        # services left to shutdown we well execute the call back and shut down the entire service
        d.chainDeferred(shutdown)
        # We need a backup plan in case something went wrong or everything is already shutdown
        # so what happens here is a logical check to execute the deferred if we have no known nodes
        # or extra services
        if not self.nodes and not self.servers: d.callback(None)
        
        