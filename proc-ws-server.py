"""
WebSocket server that reads uptime, load, memory, and bandwidth system information from /proc, pushing updates out every 500ms.

I run this on an ASUS RT-N66U router, running Tomato firmware with Optware. On boot, the router executes this script, and a status board connects, displaying the various information.

Code based on https://gist.github.com/3136208 (WebSockets server) and https://gist.github.com/1658752 (ProcNetDev)
"""

import struct
import sched
import time
import os
import json
import re
import SocketServer
from base64 import b64encode
from datetime import datetime
from hashlib import sha1
from mimetools import Message
from StringIO import StringIO

class ProcNetDev(object):
    """Parses /proc/net/dev into a usable python datastructure.
    
    By default each time you access the structure, /proc/net/dev is re-read
    and parsed so data is always current.
    
    If you want to disable this feature, pass auto_update=False to the constructor.
    
    >>> pnd = ProcNetDev()
    >>> pnd['eth0']['receive']['bytes']
    976329938704
    
    """
    
    def __init__(self, auto_update=True):
        """Opens a handle to /proc/net/dev and sets up the initial object."""
        
        #we don't wrap this in a try as we want to raise an IOError if it's not there
        self.proc = open('/proc/net/dev', 'rb')
        
        #we store our data here, this is populated in update()
        self.data = None
        self.updated = None
        self.auto_update = auto_update
        
        self.update()
    
    def __getitem__(self, key):
        """Allows accessing the interfaces as self['eth0']"""
        if self.auto_update:
            self.update()
        
        return self.data[key]
    
    def __len__(self):
        """Returns the number of interfaces available."""
        return len(self.data.keys())
    
    def __contains__(self, key):
        """Implements contains by testing for a KeyError."""
        try:
            self[key]
            return True
        except KeyError:
            return False
    
    def __nonzero__(self):
        """Eval to true if we've gottend data"""
        if self.updated:
            return True
        else:
            return False
    
    
    def __del__(self):
        """Ensure our filehandle is closed when we shutdown."""
        try:
            self.proc.close()
        except AttributeError:
            pass
    
    def update(self):
        """Updates the instances internal datastructures."""
        
        #reset our location
        self.proc.seek(0)
        
        #read our first line, and note the character positions, it's important for later
        headerline = self.proc.readline()
        if not headerline.count('|'):
            raise ValueError("Header was not in the expected format")
        
        #we need to find out where all the pipes are
        sections = []
        
        position = -1
        while position:
            last_position = position+1
            position = headerline.find('|', last_position)
            
            if position < 0:
                position = None
            
            sections.append((last_position, position, headerline[last_position:position].strip().lower()))
        
        #first section is junk "Inter-
        sections.pop(0)
        
        #now get the labels
        labelline = self.proc.readline().strip("\n")
        labels = []
        for section in sections:
            labels.append(labelline[section[0]:section[1]].split())
        
        interfaces = {}
        #now get the good stuff
        for info in self.proc.readlines():
            info = info.strip("\n")
            
            #split the data into interface name and counters
            (name, data) = info.split(":", 1)
            
            #clean them up
            name = name.strip()
            data = data.split()
            
            interfaces[name] = {}
            absolute_position = 0
            
            #loop through each section, receive, transmit, etc
            for section_number in range(len(sections)):
                tmp = {}
                
                #now loop through each label in that section
                #they aren't always the same!  transmit doesn't have multicast for example
                for label_number in range(len(labels[section_number])):
                    #for each label, we need to associate it with it's data
                    #we use absolute position since the label_number resets for each section
                    tmp[labels[section_number][label_number]] = int(data[absolute_position])
                    absolute_position += 1
                
                #push our data into the final location
                #name=eth0, section[i][2] = receive (for example)
                interfaces[name][sections[section_number][2]] = tmp
        
        #update the instance level variables.
        self.data = interfaces
        self.updated = datetime.utcnow()

class WebSocketsHandler(SocketServer.StreamRequestHandler):
    magic = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
    s = sched.scheduler(time.time, time.sleep)
    pnd = ProcNetDev()
    tx = 0
    rx = 0
    ts = 0
    
    def setup(self):
        SocketServer.StreamRequestHandler.setup(self)
        print "connection established", self.client_address
        self.handshake_done = False
        self.s.enter(0.5, 1, self.update, (self.s,))
    
    def handle(self):
        while True:
            if not self.handshake_done:
                self.handshake()
            else:
                self.read_next_message()
    
    def read_next_message(self):
        length = ord(self.rfile.read(2)[1]) & 127
        if length == 126:
            length = struct.unpack(">H", self.rfile.read(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self.rfile.read(8))[0]
        masks = [ord(byte) for byte in self.rfile.read(4)]
        decoded = ""
        for char in self.rfile.read(length):
            decoded += chr(ord(char) ^ masks[len(decoded) % 4])
        self.on_message(decoded)
    
    def send_message(self, message):
        self.request.send(chr(129))
        length = len(message)
        if length <= 125:
            self.request.send(chr(length))
        elif length >= 126 and length <= 65535:
            self.request.send(chr(126))
            self.request.send(struct.pack(">H", length))
        else:
            self.request.send(chr(127))
            self.request.send(struct.pack(">Q", length))
        self.request.send(message)
    
    def handshake(self):
        data = self.request.recv(1024).strip()
        headers = Message(StringIO(data.split('\r\n', 1)[1]))
        if headers.get("Upgrade", None) != "websocket":
            return
        print 'Handshaking...'
        key = headers['Sec-WebSocket-Key']
        digest = b64encode(sha1(key +
self.magic).hexdigest().decode('hex'))
        response = 'HTTP/1.1 101 Switching Protocols\r\n'
        response += 'Upgrade: websocket\r\n'
        response += 'Connection: Upgrade\r\n'
        response += 'Sec-WebSocket-Accept: %s\r\n\r\n' % digest
        self.handshake_done = self.request.send(response)
        self.s.run();
    
    def on_message(self, message):
        print message
    
    def update(self, sc):
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
        
        with open('/proc/loadavg', 'r') as f:
            cpu = f.readline().split()
        
        cpu.pop(-1)
        cpu.pop(-1)
        
        re_parser = re.compile(r'^(?P<key>\S*):\s*(?P<value>\d*)\s*kB')
        memory = dict()
        for line in open('/proc/meminfo'):
            match = re_parser.match(line)
            if not match:
                continue # skip lines that don't parse
            key, value = match.groups(['key', 'value'])
            memory[key] = int(value)
        
        tx = self.pnd['vlan2']['transmit']['bytes']
        rx = self.pnd['vlan2']['receive']['bytes']
        ts = time.time()
        
        diff_tx = tx - self.tx
        diff_rx = rx - self.rx
        diff_ts = ts - self.ts
        
        tx_rate = diff_tx / diff_ts
        rx_rate = diff_rx / diff_ts
        
        self.tx = tx
        self.rx = rx
        self.ts = ts
        
        message = json.dumps({'timestamp': time.time(), 'uptime': uptime_seconds, 'cpu': cpu, 'bandwidth': {'wan': {'transmit': tx, 'receive': rx, 'tx_rate': tx_rate, 'rx_rate': rx_rate}}, 'memory': {'free': memory['MemFree'], 'total': memory['MemTotal']}})
        
        #print message
        
        self.send_message(message)
        sc.enter(0.5, 1, self.update, (sc,))

if __name__ == "__main__":
    server = SocketServer.TCPServer(
        ("192.168.1.1", 9999), WebSocketsHandler)
    server.serve_forever()