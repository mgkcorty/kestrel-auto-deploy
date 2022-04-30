import platform
import os
import signal
import shutil
import json
import subprocess
from subprocess import check_output
from threading import Thread
from time import sleep

WINDOWS = 'Windows'
LINUX = 'Linux'
MACOSX = 'Darwin'

CURRENT_PLATFORM = platform.system()
CONFIG_FILE_NAME = 'kestrel-auto-deploy-config-win.json' if CURRENT_PLATFORM == WINDOWS else 'kestrel-auto-deploy-config.json'
CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), CONFIG_FILE_NAME)
CONFIG = json.load(open(CONFIG_FILE_PATH))

EXECUTABLE_FILE_NAME = CONFIG['ExecutableFileName']
VERSION_NUMBER_FILE_NAME = CONFIG['VersionNumberFileName']
DOTNET_PATH = CONFIG['DotNetPath']

REMOTE_FOLDER = CONFIG['RemoteFolder']
LOCAL_FOLDER = CONFIG['LocalFolder']

REMOTE_VERSION_NUMBER_FILE = os.path.join(REMOTE_FOLDER, VERSION_NUMBER_FILE_NAME)
LOCAL_VERSION_NUMBER_FILE = os.path.join(LOCAL_FOLDER, VERSION_NUMBER_FILE_NAME)


class ProcessInfo:
    pid = ""
    name = ""
    version = ""

    def __init__(self, pid, name, version):
        self.pid = pid
        self.name = name
        self.version = version


def copy3(src, dst, *, follow_symlinks=True):
    """Fix of copy2 method, that not works with cifs file system
    """
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))
    shutil.copyfile(src, dst, follow_symlinks=follow_symlinks)
    os.utime(dst, (os.path.getatime(dst), os.path.getmtime(dst)))
    return dst


def is_old_app_version():
    if not os.path.exists(REMOTE_VERSION_NUMBER_FILE):
        raise Exception(f'{VERSION_NUMBER_FILE_NAME} not found in remote folder {REMOTE_VERSION_NUMBER_FILE}.')
    remote_last_modify_time = os.path.getmtime(REMOTE_VERSION_NUMBER_FILE)
    local_last_modify_time = os.path.getmtime(LOCAL_VERSION_NUMBER_FILE) if os.path.exists(
        LOCAL_VERSION_NUMBER_FILE) else 0
    return remote_last_modify_time > local_last_modify_time


def represents_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False


def remove_spaces(lines):
    return list(map(lambda x: " ".join(x.strip().split()), lines))


def get_process_info(process_text):
    if CURRENT_PLATFORM == WINDOWS:
        i = len(process_text) - 1
        start_index = -1
        while i > 0:
            if process_text[i] == " ":
                start_index = i + 1
                break
            i -= 1
        pid = process_text[start_index:]
        if represents_int(pid):
            handle_utility_path = os.path.dirname(os.path.realpath(__file__))
            version_result = subprocess.run([f"handle", "-p", "dotnet.exe"], cwd=handle_utility_path,
                                            universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            version_result = list(filter(lambda x: x, version_result.stdout.split('\n')))
            version_result = remove_spaces([version_result[5]])[0]
            length = len(version_result)
            version = version_result[length - 7:]
            return ProcessInfo(pid, version, version)
        return None
    else:
        components = process_text.split(" ")
        pid = components[0]
        executable_name = components[-1]
        if represents_int(pid):
            version_result = check_output([f"pwdx {pid}"], shell=True, universal_newlines=True).split('\n')
            version_result = remove_spaces(version_result)[0]
            version = version_result.split("/")[-1]
            return ProcessInfo(pid, executable_name, version)
        return None


def get_process_list(process_name):
    try:
        if CURRENT_PLATFORM == WINDOWS:
            terminal_process_list = subprocess.getoutput(
                'wmic process where caption="dotnet.exe" get Commandline, ProcessId').split('\n')
        else:
            terminal_process_list = check_output(["ps -eo pid,cmd | grep [d]otnet"], shell=True,
                                                 universal_newlines=True).split('\n')
    except subprocess.CalledProcessError as e:
        if e.returncode != 1:  # 1 - No lines were selected.
            raise
        return []
    terminal_process_list = remove_spaces(terminal_process_list)
    process_info_list = list(map(lambda x: get_process_info(x), terminal_process_list))
    result = list(filter(lambda p: p is not None and p.name == process_name, process_info_list))
    return result


def process_runner():
    if not os.path.exists(LOCAL_VERSION_NUMBER_FILE):
        return
    file = open(LOCAL_VERSION_NUMBER_FILE, 'r')
    current_version = file.read()
    file.close()
    infos = get_process_list(EXECUTABLE_FILE_NAME)
    same_version_processes = list(filter(lambda x: x.version == current_version, infos))
    if len(same_version_processes) > 0:
        same_version_process = same_version_processes[0]
    else:
        same_version_process = None
    for info in infos:
        if same_version_process != info:
            os.kill(int(info.pid), signal.SIGTERM)
            print(f"Process killed -> {info.pid}")
    if same_version_process is not None:
        return

    site_directory = os.path.join(LOCAL_FOLDER, current_version)
    print(f"Process starting: dotnet {site_directory}")
    if CURRENT_PLATFORM == WINDOWS:
        process = subprocess.run([DOTNET_PATH, EXECUTABLE_FILE_NAME], cwd=site_directory, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        process = subprocess.run([DOTNET_PATH, EXECUTABLE_FILE_NAME], cwd=site_directory, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, preexec_fn=os.setpgrp)
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


def version_update():
    if not is_old_app_version():
        return

    file = open(REMOTE_VERSION_NUMBER_FILE, 'r')
    current_version = file.read()
    file.close()
    print(f"Start updating -> {EXECUTABLE_FILE_NAME}:{current_version}")
    if not os.path.exists(os.path.join(REMOTE_FOLDER, current_version)):
        raise Exception(f'{current_version} not found in remote folder.')
    if not os.path.exists(os.path.join(LOCAL_FOLDER, current_version)):
        os.makedirs(os.path.join(LOCAL_FOLDER, current_version))
    copytree(os.path.join(REMOTE_FOLDER, current_version), os.path.join(LOCAL_FOLDER, current_version))
    copy3(os.path.join(REMOTE_FOLDER, VERSION_NUMBER_FILE_NAME),
          os.path.join(LOCAL_FOLDER, VERSION_NUMBER_FILE_NAME))
    infos = get_process_list(EXECUTABLE_FILE_NAME)
    for info in infos:
        os.kill(int(info.pid), signal.SIGTERM)
        print(f"Process killed -> {info.pid}")
    directories = [d for d in os.listdir(LOCAL_FOLDER) if os.path.isdir(os.path.join(LOCAL_FOLDER, d))]
    for folder in directories:
        if os.path.join(LOCAL_FOLDER, folder) != os.path.join(LOCAL_FOLDER, current_version):
            shutil.rmtree(os.path.join(LOCAL_FOLDER, folder), ignore_errors=False, onerror=None)
    print(f"App is updated -> {EXECUTABLE_FILE_NAME}:{current_version}")


def process_runner_loop():
    while True:
        try:
            sleep(5)
            process_runner()
        except Exception as e:
            print(e)


def version_update_loop():
    while True:
        try:
            sleep(5)
            version_update()
        except Exception as e:
            print(e)


def main():
    if CURRENT_PLATFORM != WINDOWS and CURRENT_PLATFORM != LINUX and CURRENT_PLATFORM != MACOSX:
        raise Exception('Platform is not supported.')

    if CURRENT_PLATFORM == LINUX or CURRENT_PLATFORM == MACOSX:
        user = os.getenv("SUDO_USER")
        if user is None:
            user = os.getenv("USER")
        if user is None:
            raise Exception('Current user is None.')

    threads = [Thread(target=version_update_loop, args=()), Thread(target=process_runner_loop, args=())]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


main()
