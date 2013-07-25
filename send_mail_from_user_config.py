from email.MIMEText import MIMEText
from email.MIMEBase import MIMEBase
from email.MIMEMultipart import MIMEMultipart
from email.Charset import Charset
from email.Header import Header
from email.Utils import formatdate, make_msgid, COMMASPACE

from openerp import SUPERUSER_ID
from openerp.osv import osv, fields
from openerp.tools.translate import _
from openerp.tools import html2text
import openerp.tools as tools

from openerp.addons.base.ir.ir_mail_server import  extract_rfc2822_addresses
import logging
import threading
_logger = logging.getLogger(__name__)
class user_mail_server(osv.osv):
    _inherit = "res.users"
    _columns = {
        'x_mailpass': fields.char('Email password'),
    }
user_mail_server()

class MailDeliveryException(osv.except_osv):
    """Specific exception subclass for mail delivery errors"""
    def __init__(self, name, value):
        super(MailDeliveryException, self).__init__(name, value)

class ir_mail_server(osv.osv):
    _inherit = "ir.mail_server"
    _columns = {
    }
    def send_email(self, cr, uid, message, mail_server_id=None, smtp_server=None, smtp_port=None,
                   smtp_user=None, smtp_password=None, smtp_encryption=None, smtp_debug=False,
                   context=None):
        """Sends an email directly (no queuing).

        No retries are done, the caller should handle MailDeliveryException in order to ensure that
        the mail is never lost.

        If the mail_server_id is provided, sends using this mail server, ignoring other smtp_* arguments.
        If mail_server_id is None and smtp_server is None, use the default mail server (highest priority).
        If mail_server_id is None and smtp_server is not None, use the provided smtp_* arguments.
        If both mail_server_id and smtp_server are None, look for an 'smtp_server' value in server config,
        and fails if not found.

        :param message: the email.message.Message to send. The envelope sender will be extracted from the
                        ``Return-Path`` or ``From`` headers. The envelope recipients will be
                        extracted from the combined list of ``To``, ``CC`` and ``BCC`` headers.
        :param mail_server_id: optional id of ir.mail_server to use for sending. overrides other smtp_* arguments.
        :param smtp_server: optional hostname of SMTP server to use
        :param smtp_encryption: optional TLS mode, one of 'none', 'starttls' or 'ssl' (see ir.mail_server fields for explanation)
        :param smtp_port: optional SMTP port, if mail_server_id is not passed
        :param smtp_user: optional SMTP user, if mail_server_id is not passed
        :param smtp_password: optional SMTP password to use, if mail_server_id is not passed
        :param smtp_debug: optional SMTP debug flag, if mail_server_id is not passed
        :return: the Message-ID of the message that was just sent, if successfully sent, otherwise raises
                 MailDeliveryException and logs root cause.
        """
        smtp_from = message['Return-Path'] or message['From']
        assert smtp_from, "The Return-Path or From header is required for any outbound email"

        # The email's "Envelope From" (Return-Path), and all recipient addresses must only contain ASCII characters.
        from_rfc2822 = extract_rfc2822_addresses(smtp_from)
        assert len(from_rfc2822) == 1, "Malformed 'Return-Path' or 'From' address - it may only contain plain ASCII characters"
        smtp_from = from_rfc2822[0]
        email_to = message['To']
        email_cc = message['Cc']
        email_bcc = message['Bcc']
        smtp_to_list = filter(None, tools.flatten(map(extract_rfc2822_addresses,[email_to, email_cc, email_bcc])))
        assert smtp_to_list, "At least one valid recipient address should be specified for outgoing emails (To/Cc/Bcc)"

        # Do not actually send emails in testing mode!
        if getattr(threading.currentThread(), 'testing', False):
            _logger.log(logging.TEST, "skip sending email in test mode")
            return message['Message-Id']

        # Get SMTP Server Details from Mail Server
        mail_server = None
        if mail_server_id:
            mail_server = self.browse(cr, SUPERUSER_ID, mail_server_id)
        elif not smtp_server:
            mail_server_ids = self.search(cr, SUPERUSER_ID, [], order='sequence', limit=1)
            if mail_server_ids:
                mail_server = self.browse(cr, SUPERUSER_ID, mail_server_ids[0])

        if mail_server:
            smtp_server = mail_server.smtp_host
            smtp_user = mail_server.smtp_user
            smtp_password = mail_server.smtp_pass
            smtp_port = mail_server.smtp_port
            smtp_encryption = mail_server.smtp_encryption
            smtp_debug = smtp_debug or mail_server.smtp_debug
        else:
            # we were passed an explicit smtp_server or nothing at all
            smtp_server = smtp_server or tools.config.get('smtp_server')
            smtp_port = tools.config.get('smtp_port', 25) if smtp_port is None else smtp_port
            smtp_user = smtp_user or tools.config.get('smtp_user')
            smtp_password = smtp_password or tools.config.get('smtp_password')
            if smtp_encryption is None and tools.config.get('smtp_ssl'):
                smtp_encryption = 'starttls' # STARTTLS is the new meaning of the smtp_ssl flag as of v7.0
                
        #update by frank
        #smtp_user = smtp_from
        pid = self.pool.get('res.users').browse(cr, uid, uid, context=context).partner_id._id
        smtp_user = self.pool.get('res.partner').browse(cr, uid, pid, context=context).email
        smtp_password = self.pool.get('res.users').browse(cr, uid, uid, context=context).x_mailpass
        #/update
        
        if not smtp_server:
            raise osv.except_osv(
                         _("Missing SMTP Server"),
                         _("Please define at least one SMTP server, or provide the SMTP parameters explicitly."))

        try:
            message_id = message['Message-Id']

            # Add email in Maildir if smtp_server contains maildir.
            if smtp_server.startswith('maildir:/'):
                from mailbox import Maildir
                maildir_path = smtp_server[8:]
                mdir = Maildir(maildir_path, factory=None, create = True)
                mdir.add(message.as_string(True))
                return message_id

            try:
                smtp = self.connect(smtp_server, smtp_port, smtp_user, smtp_password, smtp_encryption or False, smtp_debug)
                #smtp = self.connect(smtp_server, smtp_port, smtp_from, smtp_password, smtp_encryption or False, smtp_debug)
                smtp.sendmail(smtp_from, smtp_to_list, message.as_string())
            finally:
                try:
                    # Close Connection of SMTP Server
                    smtp.quit()
                except Exception:
                    # ignored, just a consequence of the previous exception
                    pass
        except Exception, e:
            msg = _("Mail delivery failed via SMTP server '%s'.\n%s: %s") % (tools.ustr(smtp_server),
                                                                             e.__class__.__name__,
                                                                             tools.ustr(e))
            _logger.exception(msg)
            raise MailDeliveryException(_("Mail delivery failed"), msg)
        return message_id