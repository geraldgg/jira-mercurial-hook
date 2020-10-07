#!/usr/bin/python3.8
# jira-mercurial_hook.py - jira integration for mercurial
#
# Copyright 2020 Gerald Fauvelle <fauvellegerald@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import sys, traceback, re

sys.path.append("/usr/lib/python3.8/dist-packages")
sys.path.append('/usr/lib/python38.zip')
sys.path.append('/usr/lib/python3.8')
sys.path.append('/usr/lib/python3.8/lib-dynload')
sys.path.append('/usr/local/lib/python3.8/dist-packages')
sys.path.append('/usr/lib/python3/dist-packages')
sys.path.append(os.path.dirname(__file__))

try:
    import OpenSSL.SSL

    from jira_updater import JiraUpdater
    from mercurial.i18n import _
    from mercurial.node import short
    from mercurial import (
        cmdutil,
        error,
        mail,
        registrar,
        url,
        util,
        logcmdutil
    )
except Exception as e:
    print("Exception:" + str(e))
    print('-' * 60)
    traceback.print_exc(file=sys.stdout)
    print('-' * 60)

# Note for extension authors: ONLY specify testedwith = 'ships-with-hg-core' for
# extensions which SHIP WITH MERCURIAL. Non-mainline extensions should
# be specifying the version(s) of Mercurial they are tested with, or
# leave the attribute unspecified.
testedwith = 'ships-with-hg-core'

configtable = {}
configitem = registrar.configitem(configtable)

configitem('jira', 'apikey',
           default='',
           )
configitem('jira', 'url',
           default='',
           )
configitem('jira', 'useremail',
           default=None,
           )
configitem('jira', 'regexp',
           default=(r'bugs?\s*,?\s*(?:#|nos?\.?|num(?:ber)?s?)?\s*'
                    r'(?P<ids>(?:\d+\s*(?:,?\s*(?:and)?)?\s*)+)'
                    r'\.?\s*(?:h(?:ours?)?\s*(?P<hours>\d*(?:\.\d+)?))?')
           )
configitem('jira', 'fixregexp',
           default=(r'fix(?:es)?\s*(?:bugs?\s*)?,?\s*'
                    r'(?:nos?\.?|num(?:ber)?s?)?\s*'
                    r'(?P<ids>(?:#?\d+\s*(?:,?\s*(?:and)?)?\s*)+)'
                    r'\.?\s*(?:h(?:ours?)?\s*(?P<hours>\d*(?:\.\d+)?))?')
           )
configitem('jira', 'fixresolution',
           default='Done',
           )
configitem('jira', 'fixstatus',
           default='Accepted',
           )
configitem('jira', 'notify',
           default=configitem.dynamicdefault,
           )
configitem('jira', 'strip',
           default=0,
           )
configitem('jira', 'template',
           default=None,
           )


class jiraaccess(object):
    '''Base class for access to jira.'''

    def __init__(self, ui, repo):
        self.ui = ui
        self.repo = repo
        url = self.ui.config(_('jira'), _('url'))
        useremail = self.ui.config(_('jira'), _('useremail'))
        apikey = self.ui.config(_('jira'), _('apikey'))

        default_bug_re = (_('jira?\s*'
                            '(?P<ids>(?:#?[a-zA-Z]+\-\d+)?)'
                            '\.?\s*(?:h(?:ours?)?\s*(?P<hours>\d*(?:\.\d+)?))?'))

        default_sbug_re = (_('sjira\s*'
                             '(?P<ids>(?:#?[a-zA-Z]+\-\d+)?)'
                             '\.?\s*(?:h(?:ours?)?\s*(?P<hours>\d*(?:\.\d+)?))?'))

        self.bug_re = re.compile(self.ui.config(_('jira'), _('regexp'), default_bug_re), re.IGNORECASE)
        self.fix_re = re.compile(self.ui.config(_('jira'), _('fixregexp'), default_sbug_re), re.IGNORECASE)

        self.jira = JiraUpdater(useremail.decode('utf-8'), apikey.decode('utf-8'), url.decode('utf-8'))

    def find_bugs(self, ctx):
        '''return bugs dictionary created from commit comment.

        Extract bug info from changeset comments. Filter out any that are
        not known to jira, and any that already have a reference to
        the given changeset in their comments.
        '''
        start = 0
        hours = 0.0
        bugs = {}
        bugmatch = self.bug_re.search(ctx.description(), start)
        fixmatch = self.fix_re.search(ctx.description(), start)
        self.ui.status(_("ctx=%s\n" % str(ctx.description())))
        self.ui.status(_("bugmatch=%s, fixmatch=%s\n" % (str(bugmatch), str(fixmatch))))

        while True:
            bugattribs = {}
            if not bugmatch and not fixmatch:
                break
            if not bugmatch:
                m = fixmatch
            elif not fixmatch:
                m = bugmatch
            else:
                if bugmatch.start() > fixmatch.start():
                    m = bugmatch
                else:
                    m = fixmatch
            start = m.end()
            if m is bugmatch:
                bugmatch = self.bug_re.search(ctx.description(), start)
                if 'fix' in bugattribs:
                    del bugattribs['fix']
            else:
                fixmatch = self.fix_re.search(ctx.description(), start)
                bugattribs['fix'] = None

            try:
                ids = m.group('ids')
            except IndexError:
                ids = m.group(1)
            try:
                hours = float(m.group(_('hours')))
                bugattribs['hours'] = hours
            except IndexError:
                pass
            except TypeError:
                pass
            except ValueError:
                self.ui.status(_("%s: invalid hours\n") % m.group(_('hours')))

            self.ui.status(_("ids=%s\n" % str(ids)))

            bugs[ids] = bugattribs
        return bugs

    def update(self, bugid, ctx):
        '''update jira bug with reference to changeset.'''

        def webroot(root):
            '''strip leading prefix of repo root and turn into
            url-safe path.'''
            count = int(self.ui.config(_('jira'), _('strip')))
            root = util.pconvert(root)
            while count > 0:
                c = root.find(_('/'))
                if c == -1:
                    break
                root = root[c + 1:]
                count -= 1
            return root

        mapfile = None
        tmpl = self.ui.config(_('jira'), _('template'))
        if not tmpl:
            mapfile = self.ui.config(_('jira'), _('style'))
        if not mapfile and not tmpl:
            tmpl = _(
                '{desc|escape}\n\n------\nAuthor : {author}\nChangeset : {hgweb}/{webroot}/rev/{node|short}\nBranch : {branch}')

        spec = logcmdutil.templatespec(tmpl, mapfile)
        t = logcmdutil.changesettemplater(self.ui, self.repo, spec, False, None, False)
        self.ui.pushbuffer()
        t.show(ctx,
               changes=ctx.changeset(),
               bug=bugid,
               hgweb=self.ui.config(_('web'), _('baseurl')),
               root=self.repo.root,
               webroot=webroot(self.repo.root))
        data = self.ui.popbuffer()

        # Let's modify the data here to keep only the line talking about the bug
        lines = data.split(_('\n'))
        found = False
        end = False
        newdata = ''
        self.ui.debug(_('lines=%s\n' % lines))

        for line in lines:
            self.ui.debug(_('search in line %s\n' % str(line)))
            start = 0
            # let's assume we use a template where at the end the changeset is put,after some ---
            if end or line == _('------'):
                if not end:
                    newdata += _("\n\n")
                newdata += line + _("\n")
                end = True
            # let's see if we talk about a bug on this line
            while not found:
                m = self.bug_re.search(line, start)
                if not m:
                    self.ui.debug(_('   nothing here\n'))
                    break
                start = m.end()
                self.ui.debug(_('   found smthg %s\n' % str(start)))
                # we know we talk about a bug, check that it's the good one
                id = m.group(1)

                if not id:
                    continue
                if id == bugid:
                    newdata = line
                    found = True

        self.ui.debug(_('newdata %s\n' % str(newdata)))

        # bugid and newdata are binary, we need to decode to convert to str, jira updater only deals with str
        self.jira.update_issue(bugid.decode('utf-8'), newdata.decode('utf-8'))


def hook(ui, repo, hooktype, node=None, **kwargs):
    '''add comment to jira for each changeset that refers to a
    jira bug id. only add a comment once per bug, so same change
    seen multiple times does not fill bug with duplicate data.'''

    # GF : do not call jira hook when repository is cloned by TeamCity
    if str(repo.root).find("TeamCity") > 0 or str(repo.root).find("usr/local/backup") > 0:
        print('Not calling jira hook, repo is "' + repo.root + '"')
        return

    if node is None:
        raise error.Abort(_('hook type %s does not pass a changeset id') % hooktype)
    try:
        ui.debug(_('\n\n----------------------\nProcessing ctx %s\n' % str(repo[node])))
        ja = jiraaccess(ui, repo)
        ctx = repo[node]

        bugs = ja.find_bugs(ctx)
        ui.debug(_('Found bugs %s\n' % str(bugs)))

        if bugs:
            for bug in bugs:
                ja.update(bug, ctx)

    except Exception as e:
        raise error.Abort(_('jira error: %s') % str(e))
        pass
