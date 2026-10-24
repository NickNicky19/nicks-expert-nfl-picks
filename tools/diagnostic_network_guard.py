"""Linux x86-64 offline child-tree launcher; no network contacts in controls."""
import ctypes
import errno
import json
import os
import platform
import resource
import socket
import stat
import subprocess
import sys

DENY = (41,42,43,44,45,46,47,49,50,51,52,53,54,55,288,299,307,425,426,427)

def install():
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("Unsupported isolation architecture")
    for fd in (0,1,2):
        if stat.S_ISSOCK(os.fstat(fd).st_mode):
            raise RuntimeError("Socket standard descriptor refused")
    for item in os.listdir('/proc/self/fd'):
        if int(item) >= 3:
            try: os.close(int(item))
            except OSError: pass
    class Filter(ctypes.Structure):
        _fields_ = [('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_ = [('length',ctypes.c_ushort),('filters',ctypes.POINTER(Filter))]
    # Require native arch; kill x32/foreign calls. Deny all socket families and
    # io_uring networking routes; no pre-existing network descriptors survive.
    rules=[(0x20,0,0,4),(0x15,1,0,0xc000003e),(0x06,0,0,0x80000000),
           (0x20,0,0,0),(0x35,0,1,0x40000000),(0x06,0,0,0x80000000)]
    for call in DENY: rules += [(0x15,0,1,call),(0x06,0,0,0x00050000|errno.EPERM)]
    rules += [(0x06,0,0,0x7fff0000)]
    array=(Filter*len(rules))(*(Filter(*row) for row in rules))
    program=Program(len(rules),array)
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(38,1,0,0,0) or libc.prctl(22,2,ctypes.byref(program),0,0):
        raise OSError(ctypes.get_errno(),"Seccomp installation failed")

def controls():
    for family in (socket.AF_INET,socket.AF_INET6,socket.AF_UNIX):
        try: socket.socket(family,socket.SOCK_STREAM)
        except OSError as error:
            if error.errno != errno.EPERM: raise
        else: raise RuntimeError("Socket denial failed")
    child="import socket,errno;\ntry: socket.socket()\nexcept OSError as e: assert e.errno==errno.EPERM\nelse: raise RuntimeError('network escaped')"
    subprocess.run([sys.executable,'-c',child],check=True)
    grand="import subprocess,sys; subprocess.run([sys.executable,'-c',"+repr(child)+"],check=True)"
    subprocess.run([sys.executable,'-c',grand],check=True)
    node="const n=require('net');const s=n.connect(9,'127.0.0.1');s.on('error',e=>process.exit(e.code==='EPERM'?0:7));s.on('connect',()=>process.exit(8));setTimeout(()=>process.exit(9),2000);"
    subprocess.run(['node','-e',node],check=True,timeout=5)
    print(json.dumps({'network_isolation':'PASS','mechanism':'inherited_seccomp_v1',
        'controls':['AF_INET','AF_INET6','AF_UNIX','fresh_python_child','python_grandchild','node_loopback'],
        'provider_contacts':0}),flush=True)

if __name__=='__main__':
    install()
    controls()
    args=sys.argv[1:]
    if args and args[0]=='--': args=args[1:]
    if args: os.execvp(args[0],args)
