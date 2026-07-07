import json, urllib.request, uuid, sys

base = 'http://127.0.0.1:5000'
email = f'test_{uuid.uuid4().hex[:6]}@example.com'
data = {
    'full_name': 'Auto Tester',
    'email': email,
    'password': 'testpass123',
    'user_type': 'Student',
}
print('Registering student with email:', email)
req = urllib.request.Request(base + '/api/register', data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
try:
    resp = urllib.request.urlopen(req, timeout=10)
    print('REGISTER RESPONSE:', resp.read().decode())
except Exception as e:
    print('REGISTER ERROR:', e)
    sys.exit(1)

# Try login
ldata = {'email': email, 'password': 'testpass123', 'user_type': 'Student'}
req2 = urllib.request.Request(base + '/api/login', data=json.dumps(ldata).encode(), headers={'Content-Type': 'application/json'})
try:
    resp2 = urllib.request.urlopen(req2, timeout=10)
    print('LOGIN RESPONSE:', resp2.read().decode())
except Exception as e:
    print('LOGIN ERROR:', e)
    sys.exit(2)
