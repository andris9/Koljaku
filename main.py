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
from google.appengine.api import memcache
import logging
import math

ON_PAGE = 20

class SiteUser(db.Model):
  user = db.UserProperty()
  added = db.DateTimeProperty(auto_now_add = True)
  books = db.IntegerProperty(default=0)

class Book(db.Model):
  user = db.ReferenceProperty(reference_class = SiteUser, default = None)
  added = db.DateTimeProperty(auto_now_add = True)
  updated = db.DateTimeProperty(auto_now = True)
  title = db.StringProperty()
  chapters = db.TextProperty()

class Chapter(db.Model):
  book = db.ReferenceProperty(reference_class = Book, default = None)
  title = db.StringProperty()


def get_user(user = None):
    if not user:
        user = users.get_current_user()
    if not user:
        return False
    key = "<user-%s>" % (user.federated_identity() or user.user_id())
    user_data = memcache.get(key)
    if user_data is None:
        try:
            user_data = SiteUser.get_by_key_name(key)
        except:
            return False
        if not user_data:
            user_data = SiteUser(key_name=key)
            user_data.user = user
            user_data.put()
        memcache.set(key, user_data)
    return user_data

def get_books(user = None, page = 0):
    user_data = get_user(user)
    if not user_data:
        return False
    
    query = Book.all()
    query.filter("user =",user_data)
    query.order("-updated")
  
    results = query.fetch(ON_PAGE, page*ON_PAGE)
    return results

def get_book(key, user_data=None):
    if user_data is None:
        user_data = get_user()
    if not key:
        return False
    book = memcache.get("<book-%s>" % key)
    if book is None:
        try:
            book = Book.get(key)
        except:
            return False
        
        memcache.set("<book-%s>" % key, book)
    if not book:
        return False
    if book.user.key() != user_data.key():
        return False
    return book

def get_chapters(book):
    return False


def gen_paging(page, pages, url):
    
    if pages<2:
        return False
    
    elements = []
    for i in range(1, pages+1):
        if i == int(page):
            element = """<span class="paging-current">%s</span>""" % i
        else:
            element = """<a href="%s">%s</a>""" % (url % i, i)
        elements.append(element)
    return " ".join(elements)

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

def error404(http):
    showError(http, "Page not found")

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
        user_data = get_user()
        if not user_data:
            return errorNotLoggedIn(self)

        page = int(self.request.get("page",1))
        pages = int(math.ceil(float(user_data.books)/ON_PAGE))
        
        if page<2:
            page = 1
        elif page>pages:
            page = pages
        
        template_values = gen_template_values(self)
        template_values["books"] = get_books(page = page-1)
        template_values["book_count"] = user_data.books
        template_values["page"] = page
        template_values["pages"] = pages
        template_values["paging"] = gen_paging(page, pages, "/books?page=%s")
        
        path = os.path.join(os.path.dirname(__file__), 'views/books.html')
        self.response.out.write(template.render(path, template_values))

class BookAddHandler(webapp.RequestHandler):
    def get(self):
        user_data = get_user()
        if not user_data:
            return errorNotLoggedIn(self)
        
        template_values = gen_template_values(self)
        template_values["user_data"] = user_data
        template_values["key"] = self.request.get("title", u"")
        template_values["title"] = self.request.get("title", u"")
        template_values["page_title"] = "Add book"
        path = os.path.join(os.path.dirname(__file__), 'views/book_data.html')
        self.response.out.write(template.render(path, template_values))

class BookEditHandler(webapp.RequestHandler):
    def get(self):
        user_data = get_user()
        if not user_data:
            return errorNotLoggedIn(self)
        
        key = self.request.get("key", False)
        book = get_book(key)
        
        if not book:
            return error404(self)
        
        template_values = gen_template_values(self)
        template_values["user_data"] = user_data
        template_values["key"] = book.key()
        template_values["title"] = self.request.get("title", book.title)
        template_values["page_title"] = "Edit book"
        path = os.path.join(os.path.dirname(__file__), 'views/book_data.html')
        self.response.out.write(template.render(path, template_values))

class BookRemoveHandler(webapp.RequestHandler):
    def get(self):
        user_data = get_user()
        if not user_data:
            return errorNotLoggedIn(self)
        
        key = self.request.get("key", False)
        book = get_book(key)
        
        if not book:
            return error404(self)

        def remove_book():
            user_data.books -= 1
            book.delete()
            user_data.put()
            memcache.set("<user-%s>" % (user_data.user.federated_identity() or user_data.user.user_id()), user_data)
            memcache.delete("<book-%s>" % book.key())

        db.run_in_transaction(remove_book)
        self.redirect("/books")

class BookSaveHandler(webapp.RequestHandler):
    def post(self):
        user_data = get_user()
        if not user_data:
            return errorNotLoggedIn(self)
        
        key = self.request.get("key", False)
        title = self.request.get("title","Untitled book")

        def add_book():
            book = Book(parent=user_data)
            book.user = user_data
            book.title = title
            user_data.books += 1
            book.put()
            user_data.put()
            memcache.set("<user-%s>" % (user_data.user.federated_identity() or user_data.user.user_id()), user_data)
            memcache.set("<book-%s>" % book.key(), book)
            
        def save_book():
            book = get_book(key)
            if not book:
                return error404(self)
            book.title = title
            book.put()
            memcache.set("<book-%s>" % key, book)
            
        if not key:
            db.run_in_transaction(add_book)
        else:
            db.run_in_transaction(save_book)
        
        self.redirect("/books")




class ChapterListHandler(webapp.RequestHandler):
    def get(self):
        user_data = get_user()
        if not user_data:
            return errorNotLoggedIn(self)

        key = self.request.get("key", False)
        book = get_book(key)
        if not book:
            return error404(self)
        
        chapters = get_chapters(book)
        
        template_values = gen_template_values(self)
        template_values["book"] = book
        template_values["chapters"] = chapters
        path = os.path.join(os.path.dirname(__file__), 'views/chapters.html')
        self.response.out.write(template.render(path, template_values))
        


class LoggedHandler(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if not user:
            return errorNotLoggedIn(self)
        
        template_values = gen_template_values(self)
        template_values["user_data"] = get_user()
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
                                          ('/books', BookListHandler),
                                          ('/book-add', BookAddHandler),
                                          ('/book-edit', BookEditHandler),
                                          ('/book-save', BookSaveHandler),
                                          ('/book-remove', BookRemoveHandler),
                                          ('/chapters', ChapterListHandler)],
                                         debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
