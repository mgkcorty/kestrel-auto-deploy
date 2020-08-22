import platform
import os
import signal
import shutil
import subprocess
from subprocess import check_output
from threading import Thread
from time import sleep

remoteFolder = ''
localFolder = ''
currentPlatform = platform.system()
baseUserFolder = os.path.expanduser(r'~/')
siteDll = 'MySite.dll'
baseRemoteFolder = r'//192.168.1.1/Seagate Expansion Drive'
versionNumberFileName = 'versionNumber.txt'

class ProcessInfo:
    Pid = ""
    Name = ""
    Version = ""
    CommandLine = ""

    def __init__(self, pid, name, version, commandLine):
        self.Pid = pid
        self.Name = name
        self.Version = version
        self.CommandLine = commandLine

def copy3(src, dst, *, follow_symlinks=True):
    """Fix of copy2 method, that not works with cifs file system
    """
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))
    shutil.copyfile(src, dst, follow_symlinks=follow_symlinks)
    os.utime(dst, (os.path.getatime(dst), os.path.getmtime(dst)))
    return dst

def mountRemoteFolder():
    mountLocalFolder = os.path.join(baseUserFolder, r'Shared/Seagate Expansion Drive')
    mountResult = subprocess.getoutput(f'sudo mount.cifs "{baseRemoteFolder}" "{mountLocalFolder}" -o user=root,password=guest,dir_mode=0777,file_mode=0777')
    if not mountResult:
        return
    raise Exception(f"Mount error. {mountResult}")

def initialize():
    global remoteFolder
    global localFolder
    global baseUserFolder
    if currentPlatform == 'Windows':
        remoteFolder = os.path.join(baseRemoteFolder, r'MySite')
        localFolder = os.path.join(baseUserFolder, r'Desktop/MySite')
    elif currentPlatform == 'Linux':
        user = os.getenv("SUDO_USER")
        if user is None:
            user = os.getenv("USER")
        if user is None:
            raise Exception('Current user is None.')
        remoteFolder = os.path.join(baseUserFolder, r'Shared/Seagate Expansion Drive/MySite')
        localFolder = os.path.join(baseUserFolder, r'Desktop/MySite')
        mountRemoteFolder()
    else:
        raise Exception('RemoteFolder and LocalFolder not implemented for current platform.')

def representsInt(s):
    try:
        int(s)
        return True
    except ValueError:
        return False

def removeSpaces(lines):
    return list(map(lambda x: " ".join(x.strip().split()), lines))

def getProcessInfos(name):
    if currentPlatform == 'Windows':
        lines = subprocess.getoutput('wmic process where caption="dotnet.exe" get Commandline, ProcessId').split('\n')
        lines = list(map(lambda x: " ".join(x.strip().split()), lines))
        def getProcessInfo(s):
            i = len(s) - 1
            startIndex = -1
            while i > 0:
                if s[i] == " ":
                    startIndex = i + 1
                    break
                i -= 1
            pid = s[startIndex:]
            if representsInt(pid):
                commandArguments = s[:startIndex - 1]
                handleUtilityPath = os.path.dirname(os.path.realpath(__file__))
                versionResult = subprocess.run([f"handle", "-p", "dotnet.exe"], cwd=handleUtilityPath, universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                versionResult = list(filter(lambda x: x,versionResult.stdout.split('\n')))
                versionResult = removeSpaces([versionResult[5]])[0]
                length = len(versionResult)
                version = versionResult[length - 7:]
                return ProcessInfo(pid, name, version, commandArguments)
            return None

        processInfos = list(filter(lambda pair: pair is not None, map(lambda x: getProcessInfo(x), lines)))
        return processInfos
    elif currentPlatform == 'Linux':
        processInfos = []
        try:
            lines = check_output(["ps -eo pid,cmd | grep [d]otnet"], shell=True, universal_newlines=True).split('\n')
            lines = removeSpaces(lines)
        except subprocess.CalledProcessError as e:
            if(e.returncode != 1):
                raise
            return processInfos
        def getProcessInfo(s):
            i = 0
            endIndex = -1
            while i < len(s):
                if s[i] == " ":
                    endIndex = i
                    break
                i += 1
            pid = s[:endIndex]
            if representsInt(pid):
                commandArguments = s[endIndex + 1:]
                length = len(commandArguments)
                versionResult = check_output([f"pwdx {pid}"], shell=True, universal_newlines=True).split('\n')
                versionResult = removeSpaces(versionResult)[0]
                version = versionResult[length - 8:]
                return ProcessInfo(pid, name, version, commandArguments)
            return None

        processInfos = list(filter(lambda pair: pair is not None, map(lambda x: getProcessInfo(x), lines)))
        return processInfos
    else:
        raise Exception('getPid not implemented for current platform.')

def processRunner():
    localVersionNumberFile = os.path.join(localFolder, versionNumberFileName)
    if not os.path.exists(localVersionNumberFile):
        return
    file = open(localVersionNumberFile, 'r')
    currentVersion = file.read()
    file.close()
    infos = getProcessInfos(siteDll)
    sameVersionProcesses = list(filter(lambda x: x.Version == currentVersion, infos))
    if len(sameVersionProcesses) > 0:
        sameVersionProcess = sameVersionProcesses[0]
    else:
        sameVersionProcess = None
    for info in infos:
        if sameVersionProcess != info:
            os.kill(int(info.Pid), signal.SIGTERM)
            print(f"Process killed: {info.Pid}")
    if sameVersionProcess is not None:
        return

    siteDirectory = os.path.join(localFolder, currentVersion)
    if currentPlatform == 'Windows':
        process = subprocess.run(['dotnet', siteDll], cwd=siteDirectory, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    elif currentPlatform == 'Linux':
        print(f"Process starting: dotnet {siteDirectory}")
        process = subprocess.run(['/home/pi/dotnet-arm32/dotnet', siteDll], cwd=siteDirectory, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setpgrp)
    else:
        raise Exception('subprocess is not implemented for current platform.')
    print(process.stdout)

def remove(path):
    if os.path.isfile(path) or os.path.islink(path):
        os.remove(path)  # remove the file
    elif os.path.isdir(path):
        shutil.rmtree(path)  # remove dir and all contains

def copytree(src, dst):
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            if os.path.exists(d):
                shutil.rmtree(d)
            os.makedirs(d, exist_ok=True)
            copytree(s, d)
        else:
            if os.path.exists(d):
                os.remove(d)
            copy3(s, d)

def versionUpdate():
    remoteVersionNumberFile = os.path.join(remoteFolder, versionNumberFileName)
    localVersionNumberFile = os.path.join(localFolder, versionNumberFileName)
    if not os.path.exists(remoteVersionNumberFile):
        raise Exception(f'{versionNumberFileName} not found in remote folder {remoteVersionNumberFile}.')
    remoteLastModifyTime = os.path.getmtime(remoteVersionNumberFile)
    localLastModifyTime = os.path.getmtime(localVersionNumberFile) if os.path.exists(localVersionNumberFile) else 0
    if remoteLastModifyTime > localLastModifyTime:
        file = open(remoteVersionNumberFile, 'r')
        currentVersion = file.read()
        file.close()
        if not os.path.exists(os.path.join(remoteFolder, currentVersion)):
            raise Exception(f'{currentVersion} not found in remote folder.')
        if not os.path.exists(os.path.join(localFolder, currentVersion)):
            os.makedirs(os.path.join(localFolder, currentVersion))
        copytree(os.path.join(remoteFolder, currentVersion), os.path.join(localFolder, currentVersion))
        copy3(os.path.join(remoteFolder, versionNumberFileName), os.path.join(localFolder, versionNumberFileName))
        infos = getProcessInfos(siteDll)
        for info in infos:
            os.kill(int(info.Pid), signal.SIGTERM)
        directories = [d for d in os.listdir(localFolder) if os.path.isdir(os.path.join(localFolder, d))]
        for folder in directories:
            if (os.path.join(localFolder, folder) != os.path.join(localFolder, currentVersion)):
                shutil.rmtree(os.path.join(localFolder, folder), ignore_errors=False, onerror=None)

def processRunnerLoop():
    while True:
        try:
            sleep(5)
            processRunner()
        except Exception as e:
            print(e)

def versionUpdateLoop():
    while True:
        try:
            sleep(5)
            versionUpdate()
        except Exception as e:
            print(e)


def main():
    initialize()

    threads = []
    threads.append(Thread(target=versionUpdateLoop, args=()))
    threads.append(Thread(target=processRunnerLoop, args=()))
    for t in threads:
        t.start()
    for t in threads:
        t.join()


main()