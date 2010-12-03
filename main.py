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
import datetime
from google.appengine.api import urlfetch

from google.appengine.api import images
from google.appengine.ext import blobstore
from google.appengine.ext.webapp import blobstore_handlers

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
  description = db.StringProperty()
  isbn = db.StringProperty()
  use_index = db.BooleanProperty(default = True)
  use_toc = db.BooleanProperty(default = True)
  use_copyright = db.BooleanProperty(default = True)
  page_index = db.TextProperty()
  page_toc = db.TextProperty()
  page_copyright = db.TextProperty()
  chapters = db.TextProperty()
  cover_key = db.StringProperty()
  cover_url = db.StringProperty()
  converting = db.BooleanProperty(default = False)
  conversion_status = db.StringProperty(default="")
  conversion_time = db.DateTimeProperty()
  conversion_key = db.StringProperty()
  conversion_errors = db.TextProperty()

class Chapter(db.Model):
  book = db.ReferenceProperty(reference_class = Book, default = None)
  title = db.StringProperty()
  body = db.TextProperty()
  advanced = db.BooleanProperty(default = False)
  added = db.DateTimeProperty(auto_now_add = True)
  updated = db.DateTimeProperty(auto_now = True)

class Images(db.Model):
  book = db.ReferenceProperty(reference_class = Book, default = None)
  file = db.BlobProperty()
  added = db.DateTimeProperty(auto_now_add = True)

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

def get_book(key, user_data=None, public=False):
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
    if not public and book.user.key() != user_data.key():
        return False
    return book

def get_chapter(key, user_data=None, public = False):
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
    if not public and chapter.book.user.key() != user_data.key():
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
        "user": users.get_current_user(),
        "flash_ok": memcache.get("flash-ok"),
        "flash_error": memcache.get("flash-error")
    }
    memcache.delete("flash-ok")
    memcache.delete("flash-error")
    return template_values

def gen_toc(book, chapters=None):
    toc = get_toc_page(book)
    
    if not chapters:
        chapters = get_chapters(book)
    
    toc_template = ""
    i = 0
    for chapter in chapters:
        i += 1
        toc_template +="  1. [%s](k%s_chapter_%s.html)\n" % (chapter.title and u" %s" % chapter.title or (u"Chapter %s" % i),book.key().id(),  chapter.key().id())
            
    return string.replace(toc, "%TOC%", markdown2.markdown(toc_template))


def parse_html(html):
    # siin peaks olema ka muu loogika, lehevahetused jne
    logging.error(html)
    html = re.sub(r'<[bB][rR][^>]*?>','%%%BRBREAK%%%', html)
    html = re.sub(r'<[pP][^>]*?>(&nbsp;|\s)*?</[pP][^>]*?>','%%%EMPTYP%%%', html)
    html = re.sub(r'<[sS][uU][bB][^>]*?>','%%%SUBSTART%%%', html)
    html = re.sub(r'</[sS][uU][bB][^>]*?>','%%%SUBEND%%%', html)
    html = re.sub(r'<[sS][uU][pP][^>]*?>','%%%SUPSTART%%%', html)
    html = re.sub(r'</[sS][uU][pP][^>]*?>','%%%SUPEND%%%', html)
    
    html = re.sub(r'([tT][eE][xX][tT]-[aA][lL][iI][gG][nN]:\s*([a-zA-Z]*)[^>]*?>)',r'\1%%%ALIGN\2%%%', html)
    
    logging.error(html)
    
    md = html2markdown.html2text(html)
    title = get_title(re.sub(r'%%%[a-zA-Z]*?%%%','', md))

    md = re.sub(r'(\n>[^\r\n]*?)\r?\n',r'\1\n\n%%%REMOVEP%%%\n\n', md)

    md = re.sub(r'\n>\s*\r?\n','\n', md)
    
    md = md.replace('%%%BRBREAK%%%',"<br />")
    md = md.replace('%%%EMPTYP%%%',"<p>&nbsp;</p>")
    md = md.replace('%%%SUBSTART%%%',"<sub>")
    md = md.replace('%%%SUBEND%%%',"</sub>")
    md = md.replace('%%%SUPSTART%%%',"<sup>")
    md = md.replace('%%%SUPEND%%%',"</sup>")
    logging.error(md)

    html = markdown2.markdown(md)
    html = re.sub(r'>\s*%%%ALIGN([a-zA-Z]*?)%%%',r' style="text-align: \1">', html)
    html = re.sub(r'\n?<[pP]>\s*?%%%REMOVEP%%%\s*?</[pP]>\n?','', html)
    
    logging.error(html)
    return [html, title]

def get_title(html):
    m = re.search('^\s*##(?!#)([^\n]*)\n', html, flags = re.MULTILINE)
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
        template_values["description"] = self.request.get("description", u"")
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
        template_values["description"] = self.request.get("description", book.description)
        template_values["isbn"] = self.request.get("isbn", book.isbn)
        template_values["use_index"] = self.request.get("use_index", book.use_index)
        template_values["use_toc"] = self.request.get("use_toc", book.use_toc)
        template_values["use_copyright"] = self.request.get("use_copyright", book.use_copyright)
        template_values["page_title"] = "Edit book"
        
        template_values["book"] = book
        template_values["cover_upload"] = blobstore.create_upload_url('/cover-upload')
        
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

        if book.cover_key:
            binfo = blobstore.BlobInfo.get(book.cover_key)
            if binfo:
                binfo.delete()
        if book.conversion_key:
            binfo = blobstore.BlobInfo.get(book.conversion_key)
            if binfo:
                binfo.delete()
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
        description = self.request.get("description",u"")
        isbn = self.request.get("isbn",u"")

        use_index = bool(self.request.get("use_index"))
        use_toc = bool(self.request.get("use_toc"))
        use_copyright = bool(self.request.get("use_copyright"))

        def add_book():
            book = Book(parent=user_data)
            book.user = user_data
            book.title = title
            book.author = author
            book.description = description
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
            book.description = description
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
            toc = gen_toc(book, chapters)
        
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
        template_values["specials"] = book.use_index or book.use_toc or book.use_copyright
        logging.debug(book.use_index or book.use_toc or book.use_copyright)
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
        
        page_title = u""
        
        target = {"url": "/chapters?key=%s" % book.key()}
        
        def save_special(book):
            book.put()
            memcache.set("<book-%s>" % book.key(), book)
            target["url"] = "/chapter-%s?book=%s" %(type, book.key())
        
        def save_normal(book, chapter):
            rearrange = False
            if not chapter:
                chapter = Chapter(parent=book)
                chapter.book = book
                rearrange = True
            
            chapter.title = title
            chapter.body = contents
            chapter.put()

            target["url"] = "/chapter?key=%s" % chapter.key()
            
            if rearrange:
                chapter_queue = book.chapters and json.loads(book.chapters) or []
                chapter_queue.append(str(chapter.key()))
                book.chapters = json.dumps(chapter_queue)
                book.put()
                memcache.set("<book-%s>" % book.key(), book)

            memcache.set("<chapter-%s>" % chapter.key(), chapter)
            
        
        if type=="index":
            book.page_index = contents
            db.run_in_transaction(save_special, book)
            page_title ="Index page"
        elif type=="toc":
            book.page_toc = contents
            db.run_in_transaction(save_special, book)
            page_title ="Table of Contents page"
        elif type=="copyright":
            book.page_copyright = contents
            db.run_in_transaction(save_special, book)
            page_title ="Copyright page"
        elif type=="normal":
            chapter = get_chapter(key)
            db.run_in_transaction(save_normal, book, chapter)
            page_title ="Chapter %s" % title
        else:
            return error404(self)

        memcache.set("flash-ok", "<strong>%s</strong> saved successfully" % page_title)
        self.redirect(target["url"])

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


class GenerateHandler(webapp.RequestHandler):
    def get(self):

        key = self.request.get("key", False)
        book = get_book(key, public=True)
        if not book:
            return error404(self)
        
        chapters = get_chapters(book)
        
        template_values = gen_template_values(self)
        template_values["book"] = book
        template_values["chapters"] = chapters
        path = os.path.join(os.path.dirname(__file__), 'views/generate.html')
        self.response.out.write(template.render(path, template_values))

class GenerateItemHandler(webapp.RequestHandler):
    def get(self, name=u""):

        key = self.request.get("key", False)
        book_key = self.request.get("book", False)
        type = self.request.get("type", "chapter")
        
        title = u""
        body = u""
        
        if type=="chapter":
            chapter = get_chapter(key, public=True)
            if chapter:
                book = chapter.book
                title = chapter.title
                body = chapter.body
        else:
            book = get_book(book_key, public=True)
        
        if not book:
            return error404(self)
        
        if type=="index":
            title = book.title
            body = get_index_page(book)
        elif type=="toc":
            title = "Table of contents"
            body = gen_toc(book)
        elif type=="copyright":
            title = book.title
            body = get_copyright_page(book)
        
        chapters = get_chapters(book)
        
        template_values = gen_template_values(self)
        template_values["book"] = book
        template_values["title"] = title
        template_values["body"] = body
        
        self.response.headers['Content-Disposition'] = """attachment; filename="%s""""" % name
        path = os.path.join(os.path.dirname(__file__), 'views/generate-item.html')
        self.response.out.write(template.render(path, template_values))

class GenerateCSSHandler(webapp.RequestHandler):
    def get(self, name=u""):

        key = self.request.get("key", False)
        book = get_book(key, public=True)
        if not book:
            return error404(self)
        
        template_values = gen_template_values(self)
        template_values["book"] = book
        
        self.response.headers['Content-Type'] = "text/css; charset=utf-8"
        self.response.headers['Content-Disposition'] = """attachment; filename="%s""""" % name
        
        path = os.path.join(os.path.dirname(__file__), 'templates/KREATA.css')
        self.response.out.write(template.render(path, template_values))

class GenerateGuideHandler(webapp.RequestHandler):
    def get(self, name=u""):

        key = self.request.get("key", False)
        book = get_book(key, public=True)
        if not book:
            return error404(self)
        
        chapters = get_chapters(book)
        
        template_values = gen_template_values(self)
        template_values["book"] = book
        template_values["chapters"] = chapters
        
        self.response.headers['Content-Type'] = "application/oebps-package+xml; charset=utf-8"
        self.response.headers['Content-Disposition'] = """attachment; filename="%s""""" % name
        
        path = os.path.join(os.path.dirname(__file__), 'views/Guide.opf')
        self.response.out.write(template.render(path, template_values))


class GenerateCoverHandler(webapp.RequestHandler):
    def get(self, name=u""):
        key = self.request.get("key", False)
        book = get_book(key, public=True)
        if not book:
            return error404(self)
        
        cover = False
        if book.cover_key:
            img = images.Image(blob_key = book.cover_key)
            img.resize(width=600, height=800)
            img.im_feeling_lucky()
            cover = img.execute_transforms(output_encoding=images.PNG)
        
        if not cover:
            file = open('templates/cover.jpg')
            cover = file.read()
            file.close()
            
        
        self.response.headers['Content-Type'] = "image/jpeg"
        self.response.headers['Content-Disposition'] = """attachment; filename="%s""""" % name
        self.response.out.write(cover)


class GenerateNCXHandler(webapp.RequestHandler):
    def get(self, name=u""):
        key = self.request.get("key", False)
        book = get_book(key, public=True)
        if not book:
            return error404(self)
        
        chapters = get_chapters(book)
        
        i = 0
        
        parts = []
        
        if book.use_toc:
            i += 1
            parts.append({
                "class": "toc",
                "id": "toc",
                "order": i,
                "title": "Table of contents",
                "filename": "k%s_toc.html" % book.key().id()
            })
        if book.use_index:
            i += 1
            parts.append({
                "class": "welcome",
                "id": "index",
                "order": i,
                "title": book.title,
                "filename": "k%s_index.html" % book.key().id()
            })
        if book.use_copyright:
            i += 1
            parts.append({
                "class": "copyright",
                "id": "copyright",
                "order": i,
                "title": "Copyright information",
                "filename": "k%s_copyright.html" % book.key().id()
            })
        
        for chapter in chapters:
            i += 1
            parts.append({
                "class": "chapter",
                "id": "chapter_%s" % chapter.key().id(),
                "order": i,
                "title": chapter.title,
                "filename": "k%s_chapter_%s.html" % (book.key().id(), chapter.key().id())
            })
        
        template_values = gen_template_values(self)
        template_values["book"] = book
        template_values["chapters"] = chapters
        template_values["parts"] = parts
        
        self.response.headers['Content-Type'] = "application/x-dtbncx+xml; charset=utf-8"
        self.response.headers['Content-Disposition'] = """attachment; filename="%s""""" % name
        path = os.path.join(os.path.dirname(__file__), 'views/TOC.ncx')
        self.response.out.write(template.render(path, template_values))


class CoverUploadHandler(blobstore_handlers.BlobstoreUploadHandler):
    def post(self):
        key = self.request.get("key", None)
        
        book = get_book(key, public=True)
        upload_files = self.get_uploads('file')  # 'file' is file upload field in the form
        blob_info = upload_files[0]
        
        if not book:
            blob_info.delete()
            self.redirect('/error?r=1')
            return
        
        old_cover = book.cover_key
        try:
            book.cover_key = str(blob_info.key())
            book.cover_url = images.get_serving_url(blob_info.key(), 94)
            book.put()
            memcache.set("<book-%s>" % book.key(), book)
        except:
            blob_info.delete()
            self.redirect('/error?r=2')
            return
        
        if old_cover:
            try:
                binfo = blobstore.BlobInfo.get(old_cover)
                if binfo:
                    binfo.delete()
            except:
                pass        
        self.redirect('/book-edit?key=%s' % book.key())

class FinalRequestHandler(webapp.RequestHandler):
    def post(self):
        user_data = get_user()
        if not user_data:
            return errorNotLoggedIn(self)

        key = self.request.get("key", False)
        book = get_book(key)
        if not book:
            return error404(self)

        chapters = get_chapters(book)

        urls = []
        urls.append("http://koljaku.appspot.com/generate-cover/k%s_cover.jpg?key=%s" % (book.key().id(), book.key()))
        urls.append("http://koljaku.appspot.com/generate-guide/k%s_Guide.opf?key=%s" % (book.key().id(), book.key()))
        urls.append("http://koljaku.appspot.com/generate-ncx/k%s_KREATA%s.ncx?key=%s" % (book.key().id(),book.key().id(), book.key()))
        urls.append("http://koljaku.appspot.com/generate-css/k%s_KREATA.css?key=%s" % (book.key().id(), book.key()))

        if book.use_index:
            urls.append("http://koljaku.appspot.com/generate-item/k%s_index.html?type=index&book=%s" % (book.key().id(), book.key()))
        if book.use_toc:
            urls.append("http://koljaku.appspot.com/generate-item/k%s_toc.html?type=toc&book=%s" % (book.key().id(), book.key()))
        if book.use_copyright:
            urls.append("http://koljaku.appspot.com/generate-item/k%s_copyright.html?type=copyright&book=%s" % (book.key().id(), book.key()))

        if chapters:
            for chapter in chapters:
                urls.append("http://koljaku.appspot.com/generate-item/k%s_chapter_%s.html?type=chapter&key=%s" % (book.key().id(), chapter.key().id(), chapter.key()))

        data = {
            "files" : urls,
            "main":"k%s_Guide.opf" % book.key().id(),
            "out":"k%s_BOOK.mobi" % book.key().id(),
            "field": "file",
            "errorCallback": "http://koljaku.appspot.com/final-error?key=%s" % book.key(),
            "postCallback": blobstore.create_upload_url('/final-upload'),
            #"postCallback": "http://dev.kreata.ee/receiver.php",
            "fields":[{"name":"key", "value": "%s" % book.key()}]
        }
        logging.debug(data)
        
        api_url = "http://node.ee/node/kindle"
        form_fields = {
            "data": json.dumps(data)
        }
        form_data = urllib.urlencode(form_fields)
        result = urlfetch.fetch(url=api_url,
            payload=form_data,
            method=urlfetch.POST,
            headers={'Content-Type': 'application/x-www-form-urlencoded'})
        
        def trns():
            book.converting=True
            book.conversion_status="CONVERTING"
            book.conversion_errors = u""
            book.conversion_time = datetime.datetime.utcnow()
            book.put()
            memcache.set("<book-%s>" % book.key(), book)
        
        if result.status_code==200:
            db.run_in_transaction(trns)
            self.redirect("/chapters?key=%s" % key)
        else:
            self.redirect("/error?r=3")

class FinalErrorHandler(webapp.RequestHandler):
    def post(self):
        key = self.request.get("key", None)
        
        logging.debug(self.request.get("messages"))
        
        book = get_book(key, public=True)
        
        if not book:
            showError(self, "No such book")
            return
        
        def trns():
            book.converting=False
            book.conversion_status="ERROR"
            book.conversion_errors = self.request.get("message",u"")
            book.put()
            memcache.set("<book-%s>" % book.key(), book)
        db.run_in_transaction(trns)
        
        self.response.out.write("OK")

class FinalUploadHandler(blobstore_handlers.BlobstoreUploadHandler):
    def post(self):
        
        upload_files = self.get_uploads('file')  # 'file' is file upload field in the form
        blob_info = upload_files[0]
        
        key = self.request.get("key", None)
        book = get_book(key, public=True)
        if not book:
            blob_info.delete()
            raise NameError('HiThere')
            return
        
        old_conversion = book.conversion_key
        try:
            book.conversion_key = str(blob_info.key())
            book.conversion_status = "OK"
            book.converting = False
            book.put()
            memcache.set("<book-%s>" % book.key(), book)
        except:
            blob_info.delete()
            raise NameError('HiThere')
            return
        
        if old_conversion:
            try:
                binfo = blobstore.BlobInfo.get(old_conversion)
                if binfo:
                    binfo.delete()
            except:
                pass        
        self.redirect('/')

class FinalServeHandler(blobstore_handlers.BlobstoreDownloadHandler):
    def get(self, name=""):
        
        user_data = get_user()
        logging.debug(user_data)
        if not user_data:
            return errorNotLoggedIn(self)

        key = self.request.get("key", False)
        book = get_book(key)
        if not book:
            return error404(self)
        if not book.conversion_key:
            return error404(self)
        
        blob_info = blobstore.BlobInfo.get(book.conversion_key)
        if not book.conversion_key:
            return error404(self)
        
        self.send_blob(blob_info)


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

class ErrorHandler(webapp.RequestHandler):
    def get(self):
        showError(self, message="Error occured")
    def post(self):
        self.get()

class FlushHandler(webapp.RequestHandler):
    def get(self):
        memcache.flush_all()
        self.response.out.write("Memcache flushed!")

def redirect_from_appspot(wsgi_app):
    def redirect_if_needed(env, start_response):
        if env["HTTP_HOST"].startswith('kindle.kreata.ee'):
            import webob, urlparse
            request = webob.Request(env)
            scheme, netloc, path, query, fragment = urlparse.urlsplit(request.url)
            url = urlparse.urlunsplit([scheme, 'www.bookweed.com', path, query, fragment])
            start_response('301 Moved Permanently', [('Location', url)])
            return ["301 Moved Peramanently",
                  "Click Here %s" % url]
        else:
            return wsgi_app(env, start_response)
    return redirect_if_needed

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
                                          ('/chapter', ChapterHandler),
                                          ('/generate', GenerateHandler),
                                          (r'/generate-guide/(.*)', GenerateGuideHandler),
                                          (r'/generate-ncx/(.*)', GenerateNCXHandler),
                                          (r'/generate-cover/(.*)', GenerateCoverHandler),
                                          (r'/generate-item/(.*)', GenerateItemHandler),
                                          (r'/generate-css/(.*)', GenerateCSSHandler),
                                          ('/cover-upload', CoverUploadHandler),
                                          ('/final-upload', FinalUploadHandler),
                                          ('/final-error', FinalErrorHandler),
                                          ('/final-request', FinalRequestHandler),
                                          (r'/final-serve/(.*)', FinalServeHandler),
                                          ('/error', ErrorHandler),
                                          ('/flush', FlushHandler)],
                                         debug=True)
    application = redirect_from_appspot(application)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
