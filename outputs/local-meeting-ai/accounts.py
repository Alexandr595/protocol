"""Local users and revocable persistent sessions. No public registration."""
import contextlib,hashlib,hmac,secrets,sqlite3,time,re,threading
from http.cookies import SimpleCookie, CookieError

class Accounts:
 def __init__(self,root,initial):
  self.path=root/'state/accounts.sqlite3';self.path.parent.mkdir(exist_ok=True)
  self.lock=threading.Lock();self.attempts={}
  with self.db() as db:
   db.execute('CREATE TABLE IF NOT EXISTS users(login TEXT PRIMARY KEY,salt TEXT,hash TEXT,role TEXT)')
   db.execute('CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,login TEXT,expires REAL)')
   if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone() and initial.get('password'):
    self.insert(db,initial.get('username','meeting'),initial['password'],'admin')
 @contextlib.contextmanager
 def db(self):
  db=sqlite3.connect(self.path,timeout=15);db.row_factory=sqlite3.Row
  try:
   with db:yield db
  finally:db.close()
 @staticmethod
 def digest(password,salt):return hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
 def insert(self,db,login,password,role='user'):
  if not isinstance(login,str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{2,64}',login):raise ValueError('Логин: 2–64 латинских символа, цифры, точка, дефис или подчёркивание.')
  if not isinstance(password,str) or not 8<=len(password)<=256:raise ValueError('Пароль: от 8 до 256 символов.')
  salt=secrets.token_hex(16)
  try:db.execute('INSERT INTO users VALUES(?,?,?,?)',(login,salt,self.digest(password,salt),role))
  except sqlite3.IntegrityError:raise ValueError('Такой логин уже существует.')
 def create(self,login,password):
  with self.db() as db:self.insert(db,login,password)
 def users(self):
  with self.db() as db:return [dict(r) for r in db.execute('SELECT login,role FROM users ORDER BY login')]
 def login(self,login,password,address):
  now=time.time()
  with self.lock:
   self.attempts={k:v for k,v in self.attempts.items() if now-v[0]<600}
   since,count=self.attempts.get(address,(now,0))
   if count>=10:raise ValueError('Слишком много попыток. Повторите через 10 минут.')
   self.attempts[address]=(since,count+1)
  if not isinstance(login,str) or not isinstance(password,str) or len(password)>256:raise ValueError('Неверный логин или пароль.')
  with self.db() as db:
   row=db.execute('SELECT * FROM users WHERE login=?',(login,)).fetchone()
   candidate=self.digest(password,row['salt'] if row else '00'*16)
   if not row or not hmac.compare_digest(candidate,row['hash']):raise ValueError('Неверный логин или пароль.')
   token=secrets.token_urlsafe(32);db.execute('DELETE FROM sessions WHERE expires<?',(now,));db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),login,now+30*86400))
  with self.lock:self.attempts.pop(address,None)
  return token
 def token(self,cookie):
  try:
   jar=SimpleCookie();jar.load(cookie or '');return jar['protocol_session'].value
  except (KeyError,ValueError,CookieError):return ''
 def user(self,cookie):
  key=hashlib.sha256(self.token(cookie).encode()).hexdigest()
  with self.db() as db:
   row=db.execute('SELECT users.login,users.role FROM sessions JOIN users USING(login) WHERE token=? AND expires>?',(key,time.time())).fetchone()
   return dict(row) if row else None
 def logout(self,cookie):
  with self.db() as db:db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(self.token(cookie).encode()).hexdigest(),))
