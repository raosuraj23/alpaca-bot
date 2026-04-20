import os
import sys
import subprocess
import time

LOG_TIMEOUT = 15

python_exe = sys.executable
cmd = [python_exe, '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000', '--log-level', 'info']

print('Running:', ' '.join(cmd))
print('CWD:', os.getcwd())

p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
collected = []
start = time.time()
found_nameerror = False
found_warning = False
try:
    while True:
        line = p.stdout.readline()
        if line:
            print(line, end='')
            collected.append(line)
            ll = line.lower()
            if "_managedstockstream" in ll or "nameerror" in ll or "name '_managedstockstream'" in ll:
                found_nameerror = True
            if "equity stream" in ll and "error" in ll and "attempt" in ll:
                found_warning = True
        if time.time() - start > LOG_TIMEOUT:
            break
        if line == '' and p.poll() is not None:
            break
except KeyboardInterrupt:
    pass
finally:
    try:
        p.terminate()
        p.wait(5)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass

print('\n---COLLECTED (last 500 lines)---')
print(''.join(collected[-500:]))
print('\n---RESULT---')
print('FOUND_NAMEERROR=', found_nameerror)
print('FOUND_WARNING=', found_warning)
