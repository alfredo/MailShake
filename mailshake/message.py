# -*- coding: utf-8 -*-
from email import encoders, charset as CharSet
from email.generator import Generator
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.utils import formatdate
import mimetypes
import os
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

from .compat import to_bytestring
from .html2text import extract_text_from_html
from .utils import string_types, forbid_multi_line_headers, make_msgid


# Don't BASE64-encode UTF-8 messages
CharSet.add_charset('utf-8', CharSet.SHORTEST, None, 'utf-8')

# Default MIME type to use on attachments
DEFAULT_ATTACHMENT_MIME_TYPE = 'application/octet-stream'


class EmailMessage(object):
    """A container for email information.
    """
    content_subtype = 'plain'
    mixed_subtype = 'mixed'
    html_subtype = 'html'
    alternative_subtype = 'alternative'
    encoding = 'utf-8'

    def __init__(self, subject='', text='', from_email=None, to=None,
                 cc=None, bcc=None, reply_to=None,
                 html=None, attachments=None, headers=None,
                 text_content=None, html_content=None):
        """Initialize a single email message (which can be sent to multiple
        recipients).

        All strings used to create the message can be unicode strings
        (or UTF-8 bytestrings). The SafeMIMEText class will handle any
        necessary encoding conversions.

        `text_content` and `html_content` parameters exists for backwards
        compatibility. Use `text` and `html` instead.
        """
        to = to or []
        if isinstance(to, string_types):
            to = [to]
        self.to = list(to)

        cc = cc or []
        if isinstance(cc, string_types):
            cc = [cc]
        self.cc = list(cc)

        bcc = bcc or []
        if isinstance(bcc, string_types):
            bcc = [bcc]
        self.bcc = list(bcc)

        reply_to = reply_to or []
        if isinstance(reply_to, string_types):
            reply_to = [reply_to]
        self.reply_to = list(reply_to)

        self.from_email = from_email
        self.subject = subject
        self.attachments = attachments or []
        self.extra_headers = headers or {}

        text = text or text_content or ''
        html = html or html_content or ''
        if html and not text:
            text = extract_text_from_html(html)
        self.text = text
        self.html = html

    def render(self):
        msg = self._create_message()
        msg['Subject'] = self.subject
        msg['From'] = self.extra_headers.get('From', self.from_email)

        if not self.get_recipients():
            pass

        if self.to:
            msg['To'] = ', '.join(self.to)

        if self.cc:
            msg['Cc'] = ', '.join(self.cc)

        if self.bcc:
            msg['Bcc'] = ', '.join(self.bcc)

        # Email header names are case-insensitive (RFC 2045)
        header_names = [key.lower() for key in self.extra_headers]
        if 'date' not in header_names:
            msg['Date'] = formatdate()
        if 'message-id' not in header_names:
            msg['Message-ID'] = make_msgid()
        for name, value in self.extra_headers.items():
            if name.lower() == 'from':  # From is already handled
                continue
            msg[name] = value
        return msg

    def as_string(self, unixfrom=False):
        return self.render().as_string(unixfrom)

    def get_recipients(self):
        """Returns a list of all recipients of the email (includes direct
        addressees as well as Cc and Bcc entries).
        """
        return self.to + self.cc + self.bcc

    def attach(self, filename=None, content=None, mimetype=None):
        """Attaches a file with the given filename and content. The filename
        can be omitted and the mimetype is guessed, if not provided.

        If the first parameter is a MIMEBase subclass it is inserted directly
        into the resulting message attachments.
        """
        if isinstance(filename, MIMEBase):
            assert content == mimetype
            assert mimetype is None
            self.attachments.append(filename)
        else:
            assert content is not None
            self.attachments.append((filename, content, mimetype))

    def attach_file(self, path, mimetype=None):
        """Attaches a file from the filesystem.
        """
        filename = os.path.basename(path)
        content = open(path, 'rb').read()
        self.attach(filename, content, mimetype)

    def _create_message(self):
        text = SafeMIMEText(
            to_bytestring(self.text or '', self.encoding),
            self.content_subtype, self.encoding
        )
        msg = text

        if self.html:
            msg = SafeMIMEMultipart(_subtype=self.alternative_subtype,
                                    encoding=self.encoding)
            if self.text:
                msg.attach(text)

            if self.html:
                html = SafeMIMEText(
                    to_bytestring(self.html, self.encoding),
                    self.html_subtype, self.encoding)
                msg.attach(html)

        if self.attachments:
            _msg = SafeMIMEMultipart(_subtype=self.mixed_subtype,
                                     encoding=self.encoding)
            _msg.attach(msg)
            msg = _msg
            for attachment in self.attachments:
                if isinstance(attachment, MIMEBase):
                    msg.attach(attachment)
                else:
                    msg.attach(self._create_attachment(*attachment))

        return msg

    def _create_attachment(self, filename, content, mimetype=None):
        """Converts the filename, content, mimetype triple into a
        MIME attachment object.
        """
        if mimetype is None:
            mimetype, _ = mimetypes.guess_type(filename)
            if mimetype is None:
                mimetype = DEFAULT_ATTACHMENT_MIME_TYPE
        attachment = self._create_mime_attachment(content, mimetype)
        if filename:
            attachment.add_header('Content-Disposition', 'attachment',
                                  filename=filename)
        return attachment

    def _create_mime_attachment(self, content, mimetype):
        """Converts the content, mimetype pair into a MIME attachment object.
        """
        basetype, subtype = mimetype.split('/', 1)
        if basetype == 'text':
            attachment = SafeMIMEText(
                to_bytestring(content, self.encoding),
                subtype, self.encoding
            )
        else:
            # Encode non-text attachments with base64.
            attachment = MIMEBase(basetype, subtype)
            attachment.set_payload(content)
            encoders.encode_base64(attachment)
        return attachment


class SafeMIMEText(MIMEText):

    def __init__(self, text, subtype, charset):
        self.encoding = charset
        MIMEText.__init__(self, text, subtype, charset)

    def __setitem__(self, name, val):
        name, val = forbid_multi_line_headers(name, val, self.encoding)
        MIMEText.__setitem__(self, name, val)

    def as_string(self, unixfrom=False):
        """Return the entire formatted message as a string.
        Optional `unixfrom' when True, means include the Unix From_ envelope
        header.
        """
        fp = StringIO()
        g = Generator(fp, mangle_from_=False)
        g.flatten(self, unixfrom=unixfrom)
        return fp.getvalue()


class SafeMIMEMultipart(MIMEMultipart):

    def __init__(self, _subtype='mixed', boundary=None, _subparts=None,
                 encoding=None, **_params):
        self.encoding = encoding
        MIMEMultipart.__init__(self, _subtype, boundary, _subparts, **_params)

    def __setitem__(self, name, val):
        name, val = forbid_multi_line_headers(name, val, self.encoding)
        MIMEMultipart.__setitem__(self, name, val)

    def as_string(self, unixfrom=False):
        """Return the entire formatted message as a string.
        Optional `unixfrom' when True, means include the Unix From_ envelope
        header.
        """
        fp = StringIO()
        g = Generator(fp, mangle_from_=False)
        g.flatten(self, unixfrom=unixfrom)
        return fp.getvalue()
