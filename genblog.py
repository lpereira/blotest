#!/usr/bin/python
# Thanks to http://www.arnebrodowski.de/blog/write-your-own-restructuredtext-writer.html
# Better code formatter: https://docutils.sourceforge.io/sandbox/code-block-directive/tools/pygments-enhanced-front-ends/rst2html-pygments

from collections import defaultdict
from docutils.core import publish_parts
from docutils import nodes
from docutils.writers import html4css1
from pygments.formatters import HtmlFormatter
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from html.parser import HTMLParser
from dateutil.tz import tzlocal
from xml.etree.ElementTree import Element as XmlElement, SubElement as XmlSubElement, tostring as xml_tostring
import multiprocessing
import subprocess
import docutils.nodes
import docutils.parsers.rst.directives.admonitions
import json
import os
import re
import shutil
import html
import sys
import textwrap
import datetime
class FirstParagraph(HTMLParser):
    def __init__(self):
        super().__init__()

        self.first_paragraph = []
        self.in_p = False

    def handle_starttag(self, tag, attrs):
        if not self.first_paragraph and tag == 'p':
            self.in_p = True

    def handle_endtag(self, tag):
        if tag == 'p':
            self.in_p = False

    def handle_data(self, data):
        if self.in_p:
            self.first_paragraph.append(data)

    def get_first_paragraph(self):
        return ''.join(self.first_paragraph).replace("\n", " ")

def status(*msg):
    sys.stdout.write("\033[2K\r%s" % ' '.join(msg))
    sys.stdout.flush()

class AuthorDirective(docutils.parsers.rst.directives.admonitions.BaseAdmonition):
    node_class = nodes.author

class CategoriesDirective(docutils.parsers.rst.directives.admonitions.BaseAdmonition):
    class categories(docutils.nodes.TextElement): pass
    node_class = categories

class PostedDirective(docutils.parsers.rst.directives.admonitions.BaseAdmonition):
    class posted(docutils.nodes.TextElement): pass
    node_class = posted

class YoutubeDirective(docutils.parsers.rst.directives.admonitions.BaseAdmonition):
    class youtube(docutils.nodes.TextElement): pass
    node_class = youtube

class CommentsDirective(docutils.parsers.rst.directives.admonitions.BaseAdmonition):
    node_class = nodes.comment

class TagsDirective(docutils.parsers.rst.directives.admonitions.BaseAdmonition):
    class tags(docutils.nodes.TextElement): pass
    node_class = tags

def pygments_directive(name, arguments, options, content, lineno,
                       content_offset, block_text, state, state_machine,
		       pygments_formatter = HtmlFormatter()):
    try:
        lexer = get_lexer_by_name(arguments[0])
    except ValueError:
        # no lexer found - use the text one instead of an exception
        lexer = get_lexer_by_name('text')
    parsed = highlight(u'\n'.join(content), lexer, pygments_formatter)
    return [nodes.raw('', parsed, format='html')]
pygments_directive.arguments = (1, 0, 1)
pygments_directive.content = 1

original_assert_has_content = docutils.parsers.rst.Directive.assert_has_content
def assert_has_content(self):
    if isinstance(self, CommentsDirective):
        return
    original_assert_has_content(self)
docutils.parsers.rst.Directive.assert_has_content = assert_has_content

class BlogHTMLTranslator(html4css1.HTMLTranslator):
    def __init__(self, *args, **kwargs):
        self.tags = []
        self.found_title = False
        super(html4css1.HTMLTranslator, self).__init__(*args, **kwargs)

    def visit_comments(self, node):
        raise nodes.SkipNode
    def visit_author(self, node):
        raise nodes.SkipNode

    # FIXME: If there's category+tags, this breaks!
    def visit_categories(self, node):
        self.visit_tags(node)
    def depart_categories(self, node):
        self.depart_tags(node)
    def visit_tags(self, node):
        if not node.children:
            raise nodes.SkipNode
        if node.children[0].rawsource == 'none':
            raise nodes.SkipNode

        self.tags.extend(tag.strip().lower() for tag in node.children[0].rawsource.split(','))
        node.clear()
    def depart_tags(self, node):
        pass

    def visit_posted(self, node):
        self.body = ['<span class="time">%s</span>' % node.children[0].rawsource.strip()] + self.body
        node.clear()
    def depart_posted(self, node):
        pass    

    def visit_block_quote(self, node):
        self.body.append(self.starttag(node, 'blockquote'))
    def depart_block_quote(self, node):
        self.body.append('</blockquote>\n')

    def visit_paragraph(self, node):
        if self.should_be_compact_paragraph(node):
            self.context.append('')
        else:
            self.body.append(self.starttag(node, 'p', ''))
            self.context.append('</p>\n')
    def depart_paragraph(self, node):
        self.body.append(self.context.pop())

    def should_be_compact_paragraph(self, node):
        if isinstance(node.parent, nodes.block_quote):
            return 0
        return html4css1.HTMLTranslator.should_be_compact_paragraph(self, node)

    def visit_section(self, node):
        self.section_level += 1
    def depart_section(self, node):
        self.section_level -= 1

    def visit_title(self, node):
        if self.found_title:
            return super(html4css1.HTMLTranslator, self).visit_title(node)

        self.body.append(self.starttag(node, 'span', '', CLASS='title'))
        self.context.append('</span>\n')
        self.in_document_title = len(self.body)
        self.found_title = True

    def visit_youtube(self, node):
        video_id = node.children[0].rawsource.strip()

        self.body.append('''<iframe width="560" height="315"
                src="https://www.youtube.com/embed/%s"
                frameborder="0"
                allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture"
                allowfullscreen>
            </iframe>''' % video_id)
        node.clear()
    def depart_youtube(self, node):
        pass

class BlogHTMLWriter(html4css1.Writer):
    def __init__(self):
        self.visitor_attributes += ('tags',)
        html4css1.Writer.__init__(self)
        self.translator_class = BlogHTMLTranslator

    def assemble_parts(self):
        tags = '\n'.join('<li><a href="/topic/%s.html">%s</a></li>' % (tag, tag) for tag in set(self.tags))
        self.body = ['<ul class="tags">', tags, '</ul>'] + self.body
        self.tags = ','.join(sorted(set(self.tags)))

        super(html4css1.Writer, self).assemble_parts()

def save_html(filename, parts, is_post=True, template=open('pagetemplate.html', 'r').read()):
    tags = parts['tags'].strip()
    if tags:
        tags = tags.split(',')
        tags = '\n'.join('<li><a href="/topic/%s.html">%s</a></li>' % (tag, tag) for tag in tags)
        # FIXME: this is a big ugly hack!
        body = parts['html_body'].replace('</span><',
            '</span>' + '<ul class="tags">' + tags + '</ul>' + '<',
            1)
    else:
        if is_post:
            print('WARNING: Post "%s" has no topic' % parts['title'])
        body = parts['html_body']

    title = re.sub('<[^<]+?>', '', parts['title'])

    contents = template. \
        replace("{{contents}}", body). \
        replace("{{title}}", title)

    with open(filename, 'w') as f:
        f.write(contents)

    return contents

def gen_blog_post(writer, dirpath, filename):
    outdir = os.path.join('genblog', dirpath)

    status('Generating blog post:', os.path.join(outdir, filename))

    os.makedirs(outdir)

    contents = open(os.path.join(dirpath, filename)).read()
    year, month, day = (int(i) for i in dirpath[2:].split('/'))
    contents += "\n\n.. posted:: %04d-%02d-%02d\n\n" % (year, month, day)
    parts = publish_parts(contents, writer=writer)

    html_filename = filename.replace('.rst', '.html')
    rel_path = os.path.join(dirpath, html_filename)
    html = save_html(os.path.join('genblog', rel_path), parts)

    first_paragraph = FirstParagraph()
    first_paragraph.feed(html)

    return {
        'date': (year, month, day),
        'tags': parts['tags'].split(','),
        'filename': ('posts/' + rel_path).replace("/./", "/"),
        'title': parts['title'],
        'first_paragraph': first_paragraph.get_first_paragraph()
    }

def gen_page(writer, dirpath, filename):
    status("Generating page:", filename)

    contents = open(os.path.join(dirpath, filename)).read()
    parts = publish_parts(contents, writer=writer)
    filename = filename.replace('.rst', '.html')

    save_html(os.path.join('genblog', dirpath, filename), parts, is_post=False)

def post_link(post, include_year):
    months = {
        1:'January',
        2:'February',
        3:'March',
        4:'April',
        5:'May',
        6:'June',
        7:'July',
        8:'August',
        9:'September',
        10:'October',
        11:'November',
        12:'December'
    }
    title = html.unescape(post['title'])
    if include_year:
        date = '``Published %s, %02d, %04d``' % (months[post['date'][1]], post['date'][2], post['date'][0])
    else:
        date = '``Published %s, %02d``' % (months[post['date'][1]], post['date'][2])

    first_paragraph = textwrap.shorten(post['first_paragraph'], 256, placeholder="…")
    return '''* `%s </%s>`_\n    %s %s\n''' % (title, post['filename'], first_paragraph, date)

def gen_tags(writer, posts_by_tags):
    def topic_link(topic, n_posts):
        return '''* `%s </topic/%s.html>`_ ``%d %s``''' % (topic, topic, n_posts, "posts" if n_posts != 1 else "post")

    for tag, posts in posts_by_tags.items():
        if not tag:
            continue

        status("Generating tag", tag)
        rst = ['Posts in topic *%s*' % tag,
               '===============' + '=' * (2 + len(tag)), '']

        for post in posts:
            rst.append(post_link(post, True))

        rst.append('\n')
        rst.append('View `list of topics </topic/>`_.')

        parts = publish_parts('\n'.join(rst), writer=writer)
        save_html(os.path.join('genblog', 'topic', '%s.html' % tag), parts, is_post=False)

    rst = ['Topics',
           '======']
    for tag, posts in sorted(posts_by_tags.items(), key=lambda kv: (len(kv[1]), kv[0]), reverse=True):
        if not tag:
            continue

        rst.append(topic_link(tag, len(posts)))

    parts = publish_parts('\n'.join(rst), writer=writer)
    save_html(os.path.join('genblog', 'topic', 'index.html'), parts, is_post=False)

def gen_index(writer, posts):
    status("Generating index")

    post_by_tags = defaultdict(lambda: [])
    for posts_by_date in posts.values():
        for post in posts_by_date:
            for tag in post['tags']:
                post_by_tags[tag].append(post)

    rst = ['Most recent posts',
           '=================', '']

    last_year = -1
    for date in reversed(sorted(posts.keys())):
        year, month, day = date
        if year != last_year:
            rst.append('')
            rst.append('%04d' % year)
            rst.append('----')
            rst.append('')
            last_year = year

        for post in posts[date]:
            rst.append(post_link(post, False))

    rst.append('')
    rst.append('Posts by topic')
    rst.append('==============')
    rst.append('')
    for tag, posts in sorted(post_by_tags.items(), key=lambda kv: (len(kv[1]), kv[0]), reverse=True):
        if not tag:
            continue

        rst.append('')
        rst.append(tag)
        rst.append('-' * len(tag))
        rst.append('')

        for post in posts:
            rst.append(post_link(post, True))

    parts = publish_parts('\n'.join(rst), writer=writer)
    save_html(os.path.join('genblog', 'index.html'), parts, is_post=False)

    gen_tags(writer, post_by_tags)

def optimize_css():
    if not os.path.exists('./node_modules/.bin/csso'):
        print("To minify CSS: npm install csso-cli")
        return

    status("Minifying CSS")
    csso = subprocess.Popen(["./node_modules/.bin/csso"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    with open("blog.css", "r") as input_css:
        output = csso.communicate(input=input_css.read().encode('utf-8'))[0]
        with open("genblog/blog.css", "w") as output_css:
            output_css.write(output.decode('utf-8'))

def compress_zopfli(src):
    status("Gzipping", src)
    zopfli = subprocess.Popen(["/usr/bin/zopfli", "--gzip", src])
    zopfli.communicate()

def precompress_everything():
    if os.path.exists("/usr/bin/zopfli"):
        compress = compress_zopfli
    else:
        print("zopfli not found, not pre-compressing")
        return

    to_compress = []
    for dirpath, dirnames, filenames in os.walk('genblog'):
        for filename in filenames:
            to_compress.append(os.path.join(dirpath, filename))

    pool = multiprocessing.Pool(None)
    pool.map(compress, to_compress)
    pool.close()
    pool.join()

def minify(src):
    status("Minifying", src)
    html_minify = subprocess.Popen(["./node_modules/.bin/html-minifier",
                                    "--collapse-whitespace",
                                    "--remove-comments",
                                    "--remove-optional-tags",
                                    "--remove-redundant-attributes",
                                    "--remove-script-type-attributes",
                                    "--use-short-doctype",
                                    "--decode-entities",
                                    "--output", src,
                                    src])
    html_minify.communicate()

def minimize_html():
    if not os.path.exists("./node_modules/.bin/html-minifier"):
        print("To minify HTML: npm install html-minifier")
        return

    to_minify = []
    for dirpath, dirnames, filenames in os.walk('genblog'):
        for filename in filenames:
            if filename == 'rss.html':
                continue
            if filename.endswith('.html'):
                to_minify.append(os.path.join(dirpath, filename))

    pool = multiprocessing.Pool(None)
    pool.map(minify, to_minify)
    pool.close()
    pool.join()

def gen_rss(posts):
    def append_data(root, tag_name, data):
        element = XmlElement(tag_name)
        element.text = data
        root.append(element)

    rfc822 = "%a, %d %b %Y %H:%M:%S %z"
    tz = tzlocal()
    pub_date = datetime.datetime.now(tz)

    rss = XmlElement('rss', {'version': '2.0'})

    channel = XmlElement('channel')
    append_data(channel, 'title', 'Leandro Pereira')
    append_data(channel, 'link', 'https://tia.mat.br')
    append_data(channel, 'description', '')
    append_data(channel, 'language', 'en')
    append_data(channel, 'pubDate', pub_date.strftime(rfc822))
    rss.append(channel)

    for date, posts in sorted(posts.items(), key=lambda kv: kv[0], reverse=True):
        for post in posts:
            item = XmlElement('item')
            append_data(item, 'link', 'https://tia.mat.br/' + post['filename'])
            append_data(item, 'guid', 'https://tia.mat.br/' + post['filename'])
            append_data(item, 'title', post['title'])
            append_data(item, 'description', post['first_paragraph'])

            year, month, day = post['date']
            pub_date = datetime.datetime(year=year, month=month, day=day, tzinfo=tz)
            append_data(item, 'pubDate', pub_date.strftime(rfc822))

            channel.append(item)

    with open('genblog/rss.html', 'wb') as rss_file:
        rss_file.write(xml_tostring(rss))

if __name__ == '__main__':
    docutils.parsers.rst.directives.register_directive('author', AuthorDirective)
    docutils.parsers.rst.directives.register_directive('categories', CategoriesDirective)
    docutils.parsers.rst.directives.register_directive('tags', TagsDirective)
    docutils.parsers.rst.directives.register_directive('comments', CommentsDirective)
    docutils.parsers.rst.directives.register_directive('posted', PostedDirective)
    docutils.parsers.rst.directives.register_directive('youtube', YoutubeDirective)
    docutils.parsers.rst.directives.register_directive('code-block', pygments_directive)
    docutils.parsers.rst.directives.register_directive('code', pygments_directive)

    writer = BlogHTMLWriter()

    post_re = re.compile(r'^\./\d{4}/\d{2}/\d{2}')
    page_re = re.compile(r'^\./pages')

    try:
        shutil.rmtree("genblog")
    except FileNotFoundError:
        pass

    os.mkdir("genblog")
    os.makedirs("genblog/pages")
    os.makedirs("genblog/topic")

    # FIXME: prev/next?
    posts = defaultdict(lambda: [])
    for dirpath, dirnames, filenames in os.walk('.'):
        if post_re.match(dirpath):
            for filename in filenames:
                if not filename.endswith('.rst'):
                    continue
                post = gen_blog_post(writer, dirpath, filename)
                posts[post['date']].append(post)
        elif page_re.match(dirpath):
            for filename in filenames:
                if not filename.endswith('.rst'):
                    continue
                gen_page(writer, dirpath, filename)

    gen_index(writer, posts)
    gen_rss(posts)

    optimize_css()
    minimize_html()
    precompress_everything()

    status()
    os.system("lwan -r genblog -l 127.0.0.1:8080")
