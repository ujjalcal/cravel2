import os
import re
import random
import hashlib
import hmac
from string import letters
import json
import logging
import time

import webapp2
import jinja2
#import cravelModel
#from cravelModel import Destination

from google.appengine.ext import db
from google.appengine.ext import ndb
from google.appengine.api import memcache

template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = jinja2.Environment(loader = jinja2.FileSystemLoader(template_dir),
                               autoescape = True)

secret = 'fart'
db_timer = time.time()

def render_str(template, **params):
    t = jinja_env.get_template(template)
    return t.render(params)

def make_secure_val(val):
    return '%s|%s' % (val, hmac.new(secret, val).hexdigest())

def check_secure_val(secure_val):
    val = secure_val.split('|')[0]
    if secure_val == make_secure_val(val):
        return val

class BlogHandler(webapp2.RequestHandler):
    def write(self, *a, **kw):
        self.response.out.write(*a, **kw)

    ##injecting params
    def render_str(self, template, **params):
    	global db_timer
        params['user'] = self.user
        params['curr_time'] = round(time.time() - db_timer)
        params['path'] = self.request.path
      
        return render_str(template, **params)

    ##before actual writing inject prams##
    def render(self, template, **kw):
        self.write(self.render_str(template, **kw))

    def render_json(self, d):
        json_txt = json.dumps(d)
        self.response.headers['Content-Type'] = 'application/json; charset=UTF-8'
        self.write(json_txt)

    def set_secure_cookie(self, name, val):
        cookie_val = make_secure_val(val)
        self.response.headers.add_header(
            'Set-Cookie',
            '%s=%s; Path=/' % (name, cookie_val))

    def read_secure_cookie(self, name):
        cookie_val = self.request.cookies.get(name)
        return cookie_val and check_secure_val(cookie_val)

    def login(self, user):
        self.set_secure_cookie('user_id', str(user.key().id()))

    def logout(self):
        self.response.headers.add_header('Set-Cookie', 'user_id=; Path=/')

    def initialize(self, *a, **kw):
        webapp2.RequestHandler.initialize(self, *a, **kw)
        uid = self.read_secure_cookie('user_id')
        self.user = uid and User.by_id(int(uid))

def render_post(response, post):
    response.out.write('<b>' + post.subject + '</b><br>')
    response.out.write(post.content)

class MainPage(BlogHandler):
  def get(self):
      self.write('Hi this is the Cravel - the Youtube for Travel. <br><br> Please goto the <a href="/feed">feed</a> url below to see recent postings.')


##### user stuff
def make_salt(length = 5):
    return ''.join(random.choice(letters) for x in xrange(length))

def make_pw_hash(name, pw, salt = None):
    if not salt:
        salt = make_salt()
    h = hashlib.sha256(name + pw + salt).hexdigest()
    return '%s,%s' % (salt, h)

def valid_pw(name, password, h):
    salt = h.split(',')[0]
    return h == make_pw_hash(name, password, salt)

def users_key(group = 'default'):
    return db.Key.from_path('users', group)

class User(db.Model):
    name = db.StringProperty(required = True)
    pw_hash = db.StringProperty(required = True)
    email = db.StringProperty()

    @classmethod
    def by_id(cls, uid):
        return User.get_by_id(uid, parent = users_key())

    @classmethod
    def by_name(cls, name):
        u = User.all().filter('name =', name).get()
        return u

    @classmethod
    def register(cls, name, pw, email = None):
        pw_hash = make_pw_hash(name, pw)
        return User(parent = users_key(),
                    name = name,
                    pw_hash = pw_hash,
                    email = email)

    @classmethod
    def login(cls, name, pw):
        u = cls.by_name(name)
        if u and valid_pw(name, pw, u.pw_hash):
            return u


##### blog stuff

def blog_key(name = 'default'):
    return db.Key.from_path('blogs', name)

class Post(db.Model):
    subject = db.StringProperty(required = True)
    content = db.TextProperty(required = True)
    created = db.DateTimeProperty(auto_now_add = True)
    last_modified = db.DateTimeProperty(auto_now = True)

    def render(self):
        self._render_text = self.content.replace('\n', '<br>')
        return render_str("post.html", p = self)
    
    def as_dict(self):
        time_fmt = '%c'
        d = {'subject': self.subject,
             'content': self.content,
             'created': self.created.strftime(time_fmt),
             'last_modified': self.last_modified.strftime(time_fmt)}
        return d

    @classmethod
    def permalink(self, post_id):
        #key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        #post = db.get(key)
    	posts = list(self.allPosts())
    	for post in posts:
    		if post.key().id() == int(post_id):
        		return post
	
    @classmethod
    def allPosts(self, update=False):
    	key = 'top'
    	posts = memcache.get(key)
    	
    	if posts is None or update:
    		logging.error('DB Query')
    		posts = Post.all().order('-created')
    		#posts = list(posts)
    		memcache.set(key, posts)
	else:
		logging.error('No DB Query')
    
    	return posts


class BlogFront(BlogHandler):
    def get(self):
    	global db_timer
        #posts = Post.all().order('-created')
        posts = Post.allPosts()
        self.render('front.html', posts = posts)

class PostPage(BlogHandler):
    def get(self, post_id):
        #key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        #post = db.get(key)
        post = Post.permalink(post_id)
        logging.info(post.key().id())

        if not post:
            self.error(404)
            return

        self.render("permalink.html", post = post)

class NewPost(BlogHandler):
    def get(self):
        if self.user:
            self.render("newpost.html")
        else:
            self.redirect("/login")

    def post(self):
        global db_timer
        if not self.user:
            self.redirect('/blog')

        subject = self.request.get('subject')
        content = self.request.get('content')

        if subject and content:
            p = Post(parent = blog_key(), subject = subject, content = content)
            p.put()
            Post.allPosts(True)
            db_timer = time.time()
            self.redirect('/blog/%s' % str(p.key().id()))
            
        else:
            error = "subject and content, please!"
            self.render("newpost.html", subject=subject, content=content, error=error)


###### Unit 2 HW's
class Rot13(BlogHandler):
    def get(self):
        self.render('rot13-form.html')

    def post(self):
        rot13 = ''
        text = self.request.get('text')
        if text:
            rot13 = text.encode('rot13')

        self.render('rot13-form.html', text = rot13)


USER_RE = re.compile(r"^[a-zA-Z0-9_-]{3,20}$")
def valid_username(username):
    return username and USER_RE.match(username)

PASS_RE = re.compile(r"^.{3,20}$")
def valid_password(password):
    return password and PASS_RE.match(password)

EMAIL_RE  = re.compile(r'^[\S]+@[\S]+\.[\S]+$')
def valid_email(email):
    return not email or EMAIL_RE.match(email)

class Signup(BlogHandler):
    def get(self):
        self.render("signup-form.html")

    def post(self):
        have_error = False
        self.username = self.request.get('username')
        self.password = self.request.get('password')
        self.verify = self.request.get('verify')
        self.email = self.request.get('email')

        params = dict(username = self.username,
                      email = self.email)

        if not valid_username(self.username):
            params['error_username'] = "That's not a valid username."
            have_error = True

        if not valid_password(self.password):
            params['error_password'] = "That wasn't a valid password."
            have_error = True
        elif self.password != self.verify:
            params['error_verify'] = "Your passwords didn't match."
            have_error = True

        if not valid_email(self.email):
            params['error_email'] = "That's not a valid email."
            have_error = True

        if have_error:
            self.render('signup-form.html', **params)
        else:
            self.done()

    def done(self, *a, **kw):
        raise NotImplementedError

class Unit2Signup(Signup):
    def done(self):
        self.redirect('/unit2/welcome?username=' + self.username)

class Register(Signup):
    def done(self):
        #make sure the user doesn't already exist
        u = User.by_name(self.username)
        if u:
            msg = 'That user already exists.'
            self.render('signup-form.html', error_username = msg)
        else:
            u = User.register(self.username, self.password, self.email)
            u.put()

            self.login(u)
            self.redirect('/')

class Login(BlogHandler):
    def get(self):
        self.render('login-form.html')

    def post(self):
        username = self.request.get('username')
        password = self.request.get('password')

        u = User.login(username, password)
        if u:
            self.login(u)
            self.redirect('/')
        else:
            msg = 'Invalid login'
            self.render('login-form.html', error = msg)

class Logout(BlogHandler):
    def get(self):
        self.logout()
        self.redirect('/')

class Unit3Welcome(BlogHandler):
    def get(self):
        if self.user:
            self.render('welcome.html', username = self.user.name)
        else:
            self.redirect('/signup')


class Json(BlogHandler):
    def get(self):
        posts = Post.all().order('-created')
        #self.render('front_json.html', posts = posts)
        return self.render_json([p.as_dict() for p in posts])
    	
class PermJson(BlogHandler):
    def get(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)

        if not post:
            self.error(404)
            return
	
	self.render_json(post.as_dict())
    	
    	    	
class Flush(BlogHandler):
    def get(self):
    	memcache.flush_all()
    	self.redirect('/blog')
    	
    	
class Welcome(BlogHandler):
    def get(self):
        username = self.request.get('username')
        if valid_username(username):
            self.render('welcome.html', username = username)
        else:
            self.redirect('/unit2/signup')
            
class Wiki(db.Model):
	path = db.StringProperty(required = True)
	subject = db.StringProperty()
	content = db.TextProperty()
	version = db.IntegerProperty(default=0)
        created = db.DateTimeProperty(auto_now_add = True)
    	last_modified = db.DateTimeProperty(auto_now = True)
	
	def render(self):
	        self._render_text = self.content.replace('\n', '<br>')
        	return render_str("wiki-content.html", p = self)
	
	@classmethod
	def getWikiBypath(self, path):
		if path:
			wikiObj = db.GqlQuery('Select * from Wiki where path = \'' + path + '\' order by version desc')
			return wikiObj
	@classmethod
	def getWikiByVersion(self, path, version):
		if path:
			wikiObj = db.GqlQuery('Select * from Wiki where path = \'%s\' and version = %s' % (path, str(version)))
			return wikiObj

	def render_hist(self):
	        self._render_text = self.content.replace('\n', '<br>')
	        return render_str("wiki-history.html", q = self)
			

	
class WikiPage(BlogHandler):
   
   def get(self, npath=''):
        user_id = self.read_secure_cookie('user_id')
        
        version = self.request.get('v')
        
        path = self.request.path

        if version:
        	wikiObj = Wiki.getWikiByVersion(path, version)
        else:
	        wikiObj = Wiki.getWikiBypath(path)
        
        if wikiObj and wikiObj.count() > 0:
        	self.render('wiki.html', wiki = wikiObj[0])
    	else:
	    	self.redirect('/_edit'+path)
    	
   	

class EditWiki(BlogHandler):

   def get(self, path):
        user_id = self.read_secure_cookie('user_id')
        version = self.request.get('v')
        
        if not user_id:
        	self.redirect('/login')
        	
        path = path
        
        if version:
        	wikiObj = Wiki.getWikiByVersion(path, version)
        else:
        	wikiObj = Wiki.getWikiBypath(path)
        
        if wikiObj and wikiObj.count() > 0:
		self.render('wiki-edit.html', wiki = wikiObj[0])
	else:
   		self.render('wiki-edit.html', wiki = None)
		

      
   def post(self, path):
   	npath = path
   	content = self.request.get('content')
   	subject = self.request.get('subject')
   	
   	if subject or content:
   		wikiObj = Wiki.getWikiBypath(npath)
   		if wikiObj and wikiObj.count() >= 1:
   			wiki = wikiObj[0]
   			#wiki.subject = subject
   			#wiki.content = content
   			version = wiki.version
   			version = version + 1
   			wiki = Wiki(subject = subject, content = content, path = npath, version = version)
   		        wiki.put()
   		else:
   			wiki = Wiki(subject = subject, content = content, path = npath)
   			wiki.put()

	
	self.redirect(npath)
	
class HistoryWiki(BlogHandler):

   def get(self, path):
        user_id = self.read_secure_cookie('user_id')
        
        if not user_id:
        	self.redirect('/login')
        	
        wiki = Wiki.getWikiBypath(path)
        
        if wiki and wiki.count() > 0:
	    #self.render('wiki-history.html', wikis = wiki)
	    self.render('wiki-history_front.html', wikis = wiki)
	else:
   	    #self.render('wiki-history.html', wikis = None)
   	    self.render('wiki-history_front.html', wikis = None)
		

      
   def post(self, path):
   	npath = path
   	content = self.request.get('content')
   	subject = self.request.get('subject')
   	
   	if subject or content:
   		wikiObj = Wiki.getWikiBypath(npath)
   		if wikiObj and wikiObj.count() >= 1:
   			wiki = wikiObj[0]
   			wiki.subject = subject
   			wiki.content = content
   		        wiki.put()
   		else:
   			wiki = Wiki(subject = subject, content = content, path = npath)
   			wiki.put()
	self.redirect(npath)
	
        
        
	
class ErrorWiki(BlogHandler):
	def get(self):
		self.response.out.write("invalid url, it should be /_edit/some path")



class Destination1(ndb.Model):
	name = ndb.StringProperty()
	location = ndb.StringProperty()
	user_name = ndb.StringProperty()
	user_id = ndb.StringProperty()
	created = ndb.DateTimeProperty(auto_now_add = True)
	lastModified = ndb.DateTimeProperty(auto_now = True)
	
	def render(self):
	    logging.error('in Destination render')
	   # self._render_text = self.content.replace('\n', '<br>')
	    return render_str("cravel-content.html", d = self)

	
	@classmethod
	def getDestinationByName(self, name):
		dest = Destination1.query().filter(Destination1.name == name)
		return dest
		
	@classmethod
	def getDestinationByLocation():
		dest = ndb.GqlQuery("");
		return dest
		
	@classmethod
	def getDestinationByTypeNearLocation():
		dest = ndb.GqlQuery("");
		return dest
		
	@classmethod
	def getAllDestinations(update=True):
	    	#key = 'top'
	    	#dests = memcache.get(key)
		    	
	    	#if dests is None or update:
	    	logging.error('DB Query')
	    	dests = Destination1.query() #Destination1.all().order('-created')
	    	#	memcache.set(key, dests)
		#else:
		#	logging.error('No DB Query')
		    
    		return dests

class Trip(ndb.Model):
	name = ndb.StringProperty()
	user_name = ndb.StringProperty()
	user_id = ndb.StringProperty()
	created = ndb.DateTimeProperty(auto_now_add = True)
	lastModified = ndb.DateTimeProperty(auto_now = True)
	links = ndb.StringProperty()
	destinations = ndb.StructuredProperty(Destination1, repeated = True)
		
	def render(self):
	    logging.error('in Trip render')
	   # self._render_text = self.content.replace('\n', '<br>')
	    return render_str("cravel-content-trip.html", t = self)

	
	@classmethod
	def getTripByName(self, name):
		trips = Trip.query().filter(Trip.name == name)
		return trips
		
	@classmethod
	def getAllTrips(update=True):
	    	#key = 'top'
	    	#dests = memcache.get(key)
		    	
	    	#if dests is None or update:
	    	logging.error('DB Query')
	    	trips = Trip.query()
	    	#	memcache.set(key, dests)
		#else:
		#	logging.error('No DB Query')
		    
    		return trips
    		
class Answer(ndb.Model):
	destinations = ndb.StructuredProperty(Destination1, repeated = True)
	trips = ndb.StructuredProperty(Trip)

	user_name = ndb.StringProperty()
	user_id = ndb.StringProperty()
	created = ndb.DateTimeProperty(auto_now_add = True)
	lastModified = ndb.DateTimeProperty(auto_now = True)
	
	
	def render(self):
	    logging.error('in Answer render')
	   # self._render_text = self.content.replace('\n', '<br>')
	    return render_str("cravel-content-answer.html", a = self)

	
class Question(ndb.Model):
	question = ndb.StringProperty()
	answers = ndb.StructuredProperty(Answer)

	user_name = ndb.StringProperty()
	user_id = ndb.StringProperty()
	created = ndb.DateTimeProperty(auto_now_add = True)
	lastModified = ndb.DateTimeProperty(auto_now = True)
		
	def render(self):
	    logging.error('in Question render')
	   # self._render_text = self.content.replace('\n', '<br>')
	    return render_str("cravel-content-question.html", q = self)

	
	@classmethod
	def getQuestionByName(self, question):
		questions = Question.query().filter(Question.question == question)
		return questions
		
	@classmethod
	def getAllQuestions(update=True):
	    	#key = 'top'
	    	#dests = memcache.get(key)
		    	
	    	#if dests is None or update:
	    	logging.error('DB Query')
	    	questions = Question.query()
	    	#	memcache.set(key, dests)
		#else:
		#	logging.error('No DB Query')
		    
    		return questions


class Cravel(BlogHandler):
	def get(self):
	
		logging.error('Cravel.get')
		dest = Destination1(name = "Dum Dum", location = "India")
		dest.put()
		
		#trip = Trip(name='Ujjals Trip', user_name = 'ujjal', user_id = '1', destinations = [Destination1(name='Kolkata', location='India'), Destination1(name='Durgapur', location='India')])
		#trip.put()
		
		#question = Question(question='Ujjals Trip', user_name = 'ujjal', user_id = '1', answers = Answer(destinations = [Destination1(name='Kolkata', location='India'), Destination1(name='Durgapur', location='India')]))
		#question.put()

	        user_id = self.read_secure_cookie('user_id')
        	
	        search = self.request.get('search')
	        logging.error('search:'+search)
	        
	        if search:
	        	destinations = Destination1.getDestinationByName(search)
		else:	
			destinations = Destination1.getAllDestinations()
			
		if search:
			trips = Trip.getTripByName(search)
		else:	
			trips = Trip.getAllTrips()
		
		if search:
			questions = Question.getQuestionByName(search)
		else:	
			questions = Question.getAllQuestions()


		#logging.error(dest)
        
        	self.render('cravel.html', destinations = destinations, trips = trips, questions = questions)
		


PAGE_RE = r'(/(?:[a-zA-Z0-9_-]+/?)*)'

	
app = webapp2.WSGIApplication([#('/', MainPage),
                               #('/unit2/rot13', Rot13),
                               #('/unit2/signup', Unit2Signup),
                               #('/unit2/welcome', Welcome),
                               #('/blog/?', BlogFront),
                               #('/blog/([0-9]+)', PostPage),
                               #('/blog/newpost', NewPost),
                               #('/blog/.json', Json),
                               #('/blog/([0-9]+).json', PermJson),
                               #('/flush', Flush),
                               #('/unit3/welcome', Unit3Welcome),
                               #('/signup', Register),
                               #('/login', Login),
                               #('/logout', Logout),
			       #('/_edit' + PAGE_RE, EditWiki),
			       #('/_history' + PAGE_RE, HistoryWiki),
                               #(PAGE_RE, WikiPage),
                               ('/cravel', Cravel)
                               ],
                              debug=True)
