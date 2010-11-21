#!/usr/bin/env python
# coding: utf-8
#


from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.api import users
import diff_match_patch as dmp_module
from django.utils import simplejson as json
from google.appengine.ext import db
from google.appengine.ext.webapp import template
import os
import urllib
import markdown2
import html2markdown
import re

class Book(db.Model):
  user = db.UserProperty()
  added = db.DateTimeProperty(auto_now_add = True)
  updated = db.DateTimeProperty(auto_now = True)
  title = db.StringProperty()
  body = db.TextProperty()

def gen_template_values(http):
    template_values = {
        "user": users.get_current_user()
    }
    return template_values

def showError(http, message=None):
    template_values = gen_template_values(http)
    template_values["message"] = message or "Error"
    path = os.path.join(os.path.dirname(__file__), 'views/error.html')
    http.response.out.write(template.render(path, template_values))

def errorNotLoggedIn(http):
    showError(http, "You need to be logged in!")

class MainHandler(webapp.RequestHandler):
    def get(self):
        
        f = open('gae.html', 'r')
        html = f.read().decode("utf-8")
        
        html = html2markdown.html2text(html)
        html = markdown2.markdown(html)
        
        #/<p class="preformatted_text" -> pre/
        
        template_values = gen_template_values(self)
        template_values["html"] = html
        path = os.path.join(os.path.dirname(__file__), 'views/front.html')
        self.response.out.write(template.render(path, template_values))

class BookListHandler(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if not user:
            return errorNotLoggedIn(self)

        query = Book.all()
        query.filter("user =", user)
        query.order("-updated")

        books = query.fetch(100)

        template_values = gen_template_values(self)
        template_values["books"] = books
        
        path = os.path.join(os.path.dirname(__file__), 'views/books.html')
        self.response.out.write(template.render(path, template_values))

class LoggedHandler(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if not user:
            return errorNotLoggedIn(self)
        
        template_values = gen_template_values(self)
        path = os.path.join(os.path.dirname(__file__), 'views/logged.html')
        self.response.out.write(template.render(path, template_values))

class LogoutHandler(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if not user:
            url = "/"
        else:
            url = users.create_logout_url("/")
        self.redirect(url)
    
class LoginHandler(webapp.RequestHandler):
    def get(self):
        template_values = gen_template_values(self)
        
        target_url = self.request.get("target_url", None);
        if target_url:
            target_url = "/logged?target_url=%s" % urllib.quote_plus(target_url)
        else:
            target_url = "/logged"
        
        template_values["target_url"] = target_url
        path = os.path.join(os.path.dirname(__file__), 'views/login.html')
        self.response.out.write(template.render(path, template_values))
    
    def post(self):
        url = users.create_login_url(self.request.get("target_url", None),
                    federated_identity=self.request.get("openid", None))
        self.redirect(url)

def main():
    application = webapp.WSGIApplication([('/', MainHandler),
                                          ('/login', LoginHandler),
                                          ('/logout', LogoutHandler),
                                          ('/logged', LoggedHandler),
                                          ('/books', BookListHandler)],
                                         debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
