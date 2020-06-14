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
import docutils.nodes
import docutils.parsers.rst.directives.admonitions
import json
import os
import re
import shutil
import html

class AuthorDirective(docutils.parsers.rst.directives.admonitions.BaseAdmonition):
    node_class = nodes.author

class CategoriesDirective(docutils.parsers.rst.directives.admonitions.BaseAdmonition):
    class categories(docutils.nodes.TextElement): pass
    node_class = categories

class PostedDirective(docutils.parsers.rst.directives.admonitions.BaseAdmonition):
    class posted(docutils.nodes.TextElement): pass
    node_class = posted

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

class BlogHTMLWriter(html4css1.Writer):
    def __init__(self):
        self.visitor_attributes += ('tags',)
        html4css1.Writer.__init__(self)
        self.translator_class = BlogHTMLTranslator

    def assemble_parts(self):
        tags = '\n'.join('<li><a href="/tags/%s.html">%s</a></li>' % (tag, tag) for tag in set(self.tags))
        self.body = ['<ul class="tags">', tags, '</ul>'] + self.body
        self.tags = ','.join(set(self.tags))

        super(html4css1.Writer, self).assemble_parts()

def save_html(filename, parts, is_post=True, template=open('pagetemplate.html', 'r').read()):
    tags = parts['tags'].strip()
    if tags:
        tags = tags.split(',')
        tags = '\n'.join('<li><a href="/tags/%s.html">%s</a></li>' % (tag, tag) for tag in tags)
        body = parts['html_body'].replace('</span><',
            '</span>' + '<ul class="tags">' + tags + '</ul>' + '<',
            1)
    else:
        if is_post:
            print('WARNING: Post %s has no tag/category' % parts['title'])
        body = parts['html_body']

    contents = template. \
        replace("{{contents}}", body). \
        replace("{{title}}", parts['title'])

    with open(filename, 'w') as f:
        f.write(contents)

def gen_blog_post(writer, dirpath, filename):
    outdir = os.path.join('genblog', dirpath)

    print('Generating blog post:', os.path.join(outdir, filename))

    os.makedirs(outdir)

    contents = open(os.path.join(dirpath, filename)).read()
    year, month, day = (int(i) for i in dirpath[2:].split('/'))
    contents += "\n\n.. posted:: %04d-%02d-%02d\n\n" % (year, month, day)
    parts = publish_parts(contents, writer=writer)

    html_filename = filename.replace('.rst', '.html')
    rel_path = os.path.join(dirpath, html_filename)
    save_html(os.path.join('genblog', rel_path), parts)

    return {
        'date': (year, month, day),
        'tags': parts['tags'].split(','),
        'filename': rel_path,
        'title': parts['title']
    }

def gen_page(writer, dirpath, filename):
    print("Generating page:", filename)

    contents = open(os.path.join(dirpath, filename)).read()
    parts = publish_parts(contents, writer=writer)
    filename = filename.replace('.rst', '.html')

    save_html(os.path.join('genblog', dirpath, filename), parts, is_post=False)

def gen_tags(writer, posts_by_tags):
    print("Generating tag index")

    def post_link(post):
        title = html.unescape(post['title'])
        return '''* `%s </%s>`_''' % (title, post['filename'])

    for tag, posts in posts_by_tags.items():
        if not tag:
            continue

        print("  [%s]" % tag)
        rst = ['Tag: %s' % tag,
               '=====' + '=' * len(tag), '']

        for post in posts:
            rst.append(post_link(post))

        parts = publish_parts('\n'.join(rst), writer=writer)
        save_html(os.path.join('genblog', 'tags', '%s.html' % tag), parts, is_post=False)

def gen_index(writer, posts):
    print("Generating index")

    def post_link(post):
        title = html.unescape(post['title'])
        return '''* `%s </%s>`_''' % (title, post['filename'])

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
            rst.append(post_link(post))

    rst.append('')
    rst.append('Posts by category')
    rst.append('=================')
    rst.append('')
    for tag, posts in post_by_tags.items():
        if not tag:
            continue

        rst.append('')
        rst.append(tag)
        rst.append('-' * len(tag))
        rst.append('')

        for post in posts:
            rst.append(post_link(post))

    parts = publish_parts('\n'.join(rst), writer=writer)
    save_html(os.path.join('genblog', 'index.html'), parts, is_post=False)

    gen_tags(writer, post_by_tags)

if __name__ == '__main__':
    docutils.parsers.rst.directives.register_directive('author', AuthorDirective)
    docutils.parsers.rst.directives.register_directive('categories', CategoriesDirective)
    docutils.parsers.rst.directives.register_directive('tags', TagsDirective)
    docutils.parsers.rst.directives.register_directive('comments', CommentsDirective)
    docutils.parsers.rst.directives.register_directive('posted', PostedDirective)
    docutils.parsers.rst.directives.register_directive('code-block', pygments_directive)
    docutils.parsers.rst.directives.register_directive('code', pygments_directive)
    # TODO: youtube directive

    writer = BlogHTMLWriter()

    post_re = re.compile(r'^\./\d{4}/\d{2}/\d{2}')
    page_re = re.compile(r'^\./pages')

    try:
        shutil.rmtree("genblog")
    except FileNotFoundError:
        pass

    os.mkdir("genblog")
    os.makedirs("genblog/pages")
    os.makedirs("genblog/tags")

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