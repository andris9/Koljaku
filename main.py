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
from django.template import Context, Template # for custom templates
from django.template.loader import render_to_string
import os
import urllib
import markdown2
import html2markdown
import re
from google.appengine.api import memcache
import logging
import math
import string

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
  author = db.StringProperty()
  isbn = db.StringProperty()
  use_index = db.BooleanProperty(default = True)
  use_toc = db.BooleanProperty(default = True)
  use_copyright = db.BooleanProperty(default = True)
  page_index = db.TextProperty()
  page_toc = db.TextProperty()
  page_copyright = db.TextProperty()
  chapters = db.TextProperty()

class Chapter(db.Model):
  book = db.ReferenceProperty(reference_class = Book, default = None)
  title = db.StringProperty()
  body = db.TextProperty()

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

def get_chapter(key, user_data=None):
    if user_data is None:
        user_data = get_user()
    if not key:
        return False
    chapter = memcache.get("<chapter-%s>" % key)
    if chapter is None:
        try:
            chapter = Chapter.get(key)
        except:
            return False
        
        memcache.set("<chapter-%s>" % key, chapter)
    if not chapter:
        return False
    if chapter.book.user.key() != user_data.key():
        return False
    return chapter

def get_chapters(book):
    if book.chapters:
        chapters = json.loads(book.chapters)
        return Chapter.get(chapters)
    else:
        return False
    

def get_index_page(book):
    
    if book.page_index:
        return book.page_index

    template_values = {
        "book": book
    }
    file = open('templates/index.html')
    tmpl = file.read().decode("utf-8")
    file.close()
    return Template(tmpl.encode('utf-8')).render(Context(template_values))

def get_toc_page(book):
    
    if book.page_toc:
        return book.page_toc

    template_values = {
        "book": book
    }
    file = open('templates/toc.html')
    tmpl = file.read().decode("utf-8")
    file.close()
    return Template(tmpl.encode('utf-8')).render(Context(template_values))

def get_copyright_page(book):
    
    if book.page_copyright:
        return book.page_copyright

    template_values = {
        "book": book,
        "year": 2010
    }
    file = open('templates/copyright.html')
    tmpl = file.read().decode("utf-8")
    file.close()
    return Template(tmpl.encode('utf-8')).render(Context(template_values))

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

def parse_html(html):
    # siin peaks olema ka muu loogika, lehevahetused jne
    md = html2markdown.html2text(html)
    title = get_title(md)
    return [markdown2.markdown(md), title]

def get_title(html):
    m = re.search('^\s*##([^\n]*)\n', html, flags = re.MULTILINE)
    logging.error(m)
    if m:
        return m.group(1) or ""
    else:
        return 

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
        
        #/<p class="preformatted_text" -> pre/
        
        template_values = gen_template_values(self)
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
        template_values["key"] = self.request.get("key", u"")
        template_values["title"] = self.request.get("title", u"")
        template_values["author"] = self.request.get("author", u"")
        template_values["isbn"] = self.request.get("isbn", u"")
        template_values["use_index"] = self.request.get("use_index", False)
        template_values["use_toc"] = self.request.get("use_toc", False)
        template_values["use_copyright"] = self.request.get("use_copyright", False)
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
        template_values["author"] = self.request.get("author", book.author)
        template_values["isbn"] = self.request.get("isbn", book.isbn)
        template_values["use_index"] = self.request.get("use_index", book.use_index)
        template_values["use_toc"] = self.request.get("use_toc", book.use_toc)
        template_values["use_copyright"] = self.request.get("use_copyright", book.use_copyright)
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

        chapters = False
        if book.chapters:
            chapter_list = json.loads(book.chapters)
            chapters = Chapter.get(chapter_list)
            for chkey in chapter_list:
                memcache.delete("<chapter-%s>" % chkey)
                
        def remove_book():
            user_data.books -= 1
            book.delete()
            if chapters:
                db.delete(chapters)
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
        title = self.request.get("title",u"Untitled book")
        author = self.request.get("author",u"No author")
        isbn = self.request.get("isbn",u"")

        use_index = bool(self.request.get("use_index"))
        use_toc = bool(self.request.get("use_toc"))
        use_copyright = bool(self.request.get("use_copyright"))

        def add_book():
            book = Book(parent=user_data)
            book.user = user_data
            book.title = title
            book.author = author
            book.isbn = isbn
            
            book.use_index =  use_index
            book.use_toc = use_toc
            book.use_copyright = use_copyright
            
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
            book.author = author
            book.isbn = isbn
            
            book.use_index =  use_index
            book.use_toc = use_toc
            book.use_copyright = use_copyright
            book.put()
            memcache.set("<book-%s>" % key, book)
            
        if not key:
            db.run_in_transaction(add_book)
        else:
            db.run_in_transaction(save_book)
        
        self.redirect("/books")


class BookPreviewHandler(webapp.RequestHandler):
    def get(self):
        user_data = get_user()
        if not user_data:
            return errorNotLoggedIn(self)

        key = self.request.get("key", False)
        book = get_book(key)
        if not book:
            return error404(self)
        
        chapters = get_chapters(book)
        
        index = copyright = toc = False

        if book.use_index:
            index = get_index_page(book)
        
        if book.use_copyright:
            copyright = get_copyright_page(book)
        
        if book.use_toc:
            toc = get_toc_page(book)
            
            toc_template = ""
            i = 0
            for chapter in chapters:
                i += 1
                toc_template +="  1. [%s](#ch-%s)\n" % (chapter.title and u" %s" % chapter.title or (u"Chapter %s" % i), chapter.key().id())
            
            toc = string.replace(toc, "%TOC%", markdown2.markdown(toc_template))
        
        template_values = gen_template_values(self)
        template_values["book"] = book
        template_values["chapters"] = chapters
        
        template_values["index"] = index
        template_values["copyright"] = copyright
        template_values["toc"] = toc
        
        type = self.request.get("export", False) and "export" or "preview"
        
        path = os.path.join(os.path.dirname(__file__), 'views/%s.html' % type)
        self.response.out.write(template.render(path, template_values))
        

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
        

class ChapterIndexHandler(webapp.RequestHandler):
    def get(self):
        user_data = get_user()
        if not user_data:
            return errorNotLoggedIn(self)

        key = self.request.get("book", False)
        book = get_book(key)
        if not book:
            return error404(self)
        
        index = get_index_page(book)
        
        template_values = gen_template_values(self)
        template_values["book"] = book
        template_values["contents"] = index
        template_values["title"] = "Index page"
        template_values["type"] = "index"
        path = os.path.join(os.path.dirname(__file__), 'views/editor.html')
        self.response.out.write(template.render(path, template_values))
        
class ChapterTOCHandler(webapp.RequestHandler):
    def get(self):
        user_data = get_user()
        if not user_data:
            return errorNotLoggedIn(self)

        key = self.request.get("book", False)
        book = get_book(key)
        if not book:
            return error404(self)
        
        toc = get_toc_page(book)
        
        template_values = gen_template_values(self)
        template_values["book"] = book
        template_values["contents"] = toc
        template_values["title"] = "Table of contents"
        template_values["type"] = "toc"
        path = os.path.join(os.path.dirname(__file__), 'views/editor.html')
        self.response.out.write(template.render(path, template_values))
        
class ChapterCopyrightHandler(webapp.RequestHandler):
    def get(self):
        user_data = get_user()
        if not user_data:
            return errorNotLoggedIn(self)

        key = self.request.get("book", False)
        book = get_book(key)
        if not book:
            return error404(self)
        
        copyright = get_copyright_page(book)
        
        template_values = gen_template_values(self)
        template_values["book"] = book
        template_values["contents"] = copyright
        template_values["title"] = "Copyright page"
        template_values["type"] = "copyright"
        path = os.path.join(os.path.dirname(__file__), 'views/editor.html')
        self.response.out.write(template.render(path, template_values))

class ChapterSaveHandler(webapp.RequestHandler):
    def post(self):
        user_data = get_user()
        if not user_data:
            return errorNotLoggedIn(self)

        key = self.request.get("book", False)
        book = get_book(key)
        if not book:
            return error404(self)

        type = self.request.get("type", False)
        key = self.request.get("key", False)
        
        contents_md = self.request.get("contents",u"")
        data = parse_html(contents_md)
        contents = data[0]
        title = data[1]
        
        def save_special(book):
            book.put()
            memcache.set("<book-%s>" % book.key(), book)
        
        def save_normal(book, chapter):
            rearrange = False
            if not chapter:
                chapter = Chapter(parent=book)
                chapter.book = book
                rearrange = True
            
            chapter.title = title
            chapter.body = contents
            chapter.put()
            
            if rearrange:
                chapter_queue = book.chapters and json.loads(book.chapters) or []
                chapter_queue.append(str(chapter.key()))
                book.chapters = json.dumps(chapter_queue)
                book.put()
                memcache.set("<book-%s>" % book.key(), book)
            memcache.set("<chapter-%s>" % chapter.key(), chapter)
            
        
        if type=="index":
            book.page_index = contents
            save_special(book)
        elif type=="toc":
            book.page_toc = contents
            save_special(book)
        elif type=="copyright":
            book.page_copyright = contents
            save_special(book)
        elif type=="normal":
            chapter = get_chapter(key)
            db.run_in_transaction(save_normal, book, chapter)
        else:
            return error404(self)

        
        self.redirect("/chapters?key=%s" % book.key())

class ChapterHandler(webapp.RequestHandler):
    def get(self):
        user_data = get_user()
        if not user_data:
            return errorNotLoggedIn(self)

        key = self.request.get("key", False)
        
        chapter = get_chapter(key)
        if not chapter:
            return error404(self)
        book = get_book(chapter.book.key())
        if not book:
            return error404(self)

        title = self.request.get("title", chapter.title)
        contents = self.request.get("contents", chapter.body)
        
        template_values = gen_template_values(self)
        template_values["book"] = book
        template_values["contents"] = contents
        template_values["title"] = title
        template_values["type"] = "normal"
        template_values["key"] = chapter.key()
        path = os.path.join(os.path.dirname(__file__), 'views/editor.html')
        self.response.out.write(template.render(path, template_values))

class ChapterAddHandler(webapp.RequestHandler):
    def get(self):
        user_data = get_user()
        if not user_data:
            return errorNotLoggedIn(self)

        key = self.request.get("book", False)
        book = get_book(key)
        if not book:
            return error404(self)
        
        template_values = gen_template_values(self)
        template_values["book"] = book
        template_values["contents"] = parse_html(self.request.get("contents",u"<h2>Chapter title</h2><p>First paragraph</p>"))[0]
        template_values["title"] = u"New chapter"
        template_values["type"] = "normal"
        template_values["key"] = ""
        path = os.path.join(os.path.dirname(__file__), 'views/editor.html')
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
                                          ('/book-preview', BookPreviewHandler),
                                          ('/chapters', ChapterListHandler),
                                          ('/chapter-index', ChapterIndexHandler),
                                          ('/chapter-toc', ChapterTOCHandler),
                                          ('/chapter-copyright', ChapterCopyrightHandler),
                                          ('/chapter-save', ChapterSaveHandler),
                                          ('/chapter-add', ChapterAddHandler),
                                          ('/chapter', ChapterHandler)],
                                         debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
