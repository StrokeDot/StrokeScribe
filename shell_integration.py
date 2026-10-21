"""Bounded, current-user local delivery for installed shell-open requests."""
import hashlib,json,tempfile
from pathlib import Path
from PySide6.QtCore import QObject,Signal,QLockFile
from PySide6.QtNetwork import QLocalServer,QLocalSocket

MAX_REQUEST=32768

def server_name(root):
    identity=str(Path(root).resolve()).casefold()+'|'+str(Path.home()).casefold()
    return 'StrokeScribe-'+hashlib.sha256(identity.encode()).hexdigest()[:32]

class ProjectBroker(QObject):
    requested=Signal(object)
    def __init__(self,name,parent=None):
        super().__init__(parent)
        self.name=name;self.server=QLocalServer(self);self.owner=False;self.buffers={}
        lockname=hashlib.sha256(name.encode()).hexdigest()+'.lock'
        self.lock=QLockFile(str(Path(tempfile.gettempdir())/lockname));self.lock.setStaleLockTime(0)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept)
    def claim(self):
        if self.owner:return True
        if not self.lock.tryLock(0):return False
        self.owner=self.server.listen(self.name)
        if not self.owner:self.lock.unlock()
        return self.owner
    @staticmethod
    def forward(name,path):
        if path is not None and (not isinstance(path,str) or '\0' in path):return False
        data=json.dumps({'path':path},ensure_ascii=False).encode('utf-8')+b'\n'
        if len(data)>MAX_REQUEST:return False
        socket=QLocalSocket();socket.connectToServer(name)
        if not socket.waitForConnected(1500):
            import logging
            logging.getLogger(__name__).warning('Project request connection failed: %s',socket.errorString())
            return False
        socket.write(data)
        while socket.bytesToWrite():
            if not socket.waitForBytesWritten(1500) and socket.bytesToWrite():
                import logging
                logging.getLogger(__name__).warning('Project request write failed: %s (%s bytes pending)',socket.errorString(),socket.bytesToWrite())
                socket.abort();return False
        socket.disconnectFromServer()
        return True
    def _accept(self):
        while self.server.hasPendingConnections():
            socket=self.server.nextPendingConnection()
            socket.setReadBufferSize(MAX_REQUEST+1);self.buffers[socket]=b''
            socket.readyRead.connect(lambda s=socket:self._read(s))
            socket.disconnected.connect(lambda s=socket:self._closed(s))
            self._read(socket)
    def _read(self,socket):
        if socket not in self.buffers:return
        data=self.buffers[socket]+bytes(socket.read(MAX_REQUEST+1-len(self.buffers[socket])))
        if len(data)>MAX_REQUEST:socket.abort();return
        if b'\n' not in data:self.buffers[socket]=data;return
        raw,remaining=data.split(b'\n',1)
        self.buffers.pop(socket,None)
        try:
            value=json.loads(raw)
            if not isinstance(value,dict) or set(value)!={'path'} or remaining.strip():raise ValueError()
            path=value['path']
            if path is not None and (not isinstance(path,str) or '\0' in path):raise ValueError()
        except (ValueError,UnicodeError):
            socket.abort();return
        self.requested.emit(path)
        socket.disconnectFromServer()
    def _closed(self,socket):
        # A peer may close immediately after writing its complete request.
        self._read(socket)
        self.buffers.pop(socket,None);socket.deleteLater()
    def close(self):
        for socket in list(self.buffers):socket.abort()
        self.buffers.clear()
        if self.owner:
            self.server.close();self.owner=False;self.lock.unlock()
