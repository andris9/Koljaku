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


class MainHandler(webapp.RequestHandler):
    def get(self):
        template_values = {}
        path = os.path.join(os.path.dirname(__file__), 'views/main.html')
        self.response.out.write(template.render(path, template_values))
    

def main():
    application = webapp.WSGIApplication([('/', MainHandler)],
                                         debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
