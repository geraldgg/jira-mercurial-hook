#!/usr/bin/python3.8
# jira-mercurial_hook.py - jira integration for mercurial
#
# Copyright 2020 Gerald Fauvelle <fauvellegerald@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

'''hooks for integrating with Jira

This hook extension adds comments on issues in Jira when changesets
that refer to issue by Jira ID are seen. The comment is formatted using
the Mercurial template mechanism.

The bug references can optionally include an update for jira of the
hours spent working on the bug. Bugs can also be marked fixed.

Access is done via the atlassian python api (REST-API) and requires
a jira username and api key specified in the configuration. Comments
are made under the given username or the user associated with the apikey in jira.

Configuration items common to all access modes:

jira.regexp
  Regular expression to match bug IDs for update in changeset commit message.
  It must contain one "()" named group ``<ids>`` containing the bug
  IDs separated by non-digit characters. It may also contain
  a named group ``<hours>`` with a floating-point number giving the
  hours worked on the bug. If no named groups are present, the first
  "()" group is assumed to contain the bug IDs, second group is assumned to
  contain hours. The default expression matches ``jira ABCD-1234``,
  ``jira no. ABCD-1234``, ``jira number ABCD-1234``, ``jira ABCD-1234,5678``,
  ``jira ABCD-1234 and ABCD-5678`` and variations thereof, followed by an hours
   number prefixed by ``h`` or ``hours``, e.g. ``hours 1.5``.
   Matching is case insensitive.

jira.fixregexp
  Same as previous regexp, except that sjira is searched insteaod of jira

jira.fixstatus
  The status to set a bug to when marking fixed. Default ``Accepted``.

jira.fixresolution
  The resolution to set a bug to when marking fixed. Default ``Resolved``.

jira.template
  Template to use when formatting comments. Overrides style if
  specified. In addition to the usual Mercurial keywords, the
  extension specifies:

  :``{bug}``:     The jira bug ID.
  :``{root}``:    The full pathname of the Mercurial repository.
  :``{webroot}``: Stripped pathname of the Mercurial repository.
  :``{hgweb}``:   Base URL for browsing Mercurial repositories.

  Default '{desc|escape}\n\n'
          '------\n'
          'Author : {author}\n'
          'Changeset : {hgweb}/{webroot}/rev/{node|short}\n'
          'Branch : {branch}'

jira.strip
  The number of path separator characters to strip from the front of
  the Mercurial repository path (``{root}`` in templates) to produce
  ``{webroot}``. For example, a repository with ``{root}``
  ``/var/local/my-project`` with a strip of 2 gives a value for
  ``{webroot}`` of ``my-project``. Default 0.

web.baseurl
  Base URL for browsing Mercurial repositories. Referenced from
  templates as ``{hgweb}``.

jira.url
  The base URL for the jira installation.
  Default ````.

jira.possibleprojects
  List of possible projects in Jira, separated by a comma. If an issue id
  is in a project not in this list, it won't be updated
  example: ABCD,EFGH
  Default ````.

jira.useremail
  The user email to use to log into jira.

jira.apikey
  An apikey generated on the jira instance for api access.
  Using an apikey removes the need to store the user and password
  options.

Activating the extension::

    [extensions]
    jira =

    [hooks]
    # run jira hook on every change pulled or pushed in here
    incoming.jira = python:hgext.jira.hook

    [jira]
    url=https://myjira.atlassian.net/
    useremail=user@company.com
    apikey=123456798ABCDEF
    strip=5
    template = {desc|escape}\n\n------\nAuthor : {author}\nChangeset : {hgweb}/{webroot}/rev/{node|short}\nBranch : {branch}

'''

import sys, traceback, re, os

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
        configitems,
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
           default=('jira?\s*'
                    '(?P<ids>(?:#?[a-zA-Z]+\-\d+)?)'
                    '\s*\.?\,?\s*(?:h(?:ours?)?\s*(?P<hours>\d*(?:\.\d+)?))?')
           )
configitem('jira', 'fixregexp',
           default=('sjira\s*'
                    '(?P<ids>(?:#?[a-zA-Z]+\-\d+)?)'
                    '\s*\.?\,?\s*(?:h(?:ours?)?\s*(?P<hours>\d*(?:\.\d+)?))?')
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
configitem('jira', 'possibleprojects',
           default=None,
           )

def config(ui, key):
    return _(ui.config(_('jira'), _(key), configtable['jira'][key].default))

class jiraaccess(object):
    '''Base class for access to jira.'''

    def __init__(self, ui, repo):
        self.ui = ui
        self.repo = repo
        url = config(ui, 'url')
        useremail = config(ui, 'useremail')
        apikey = config(ui, 'apikey')

        self.bug_re = re.compile(config(ui, 'regexp'), re.IGNORECASE)
        self.fix_re = re.compile(config(ui, 'fixregexp'), re.IGNORECASE)

        self.jira = JiraUpdater(useremail.decode('utf-8'), apikey.decode('utf-8'), url.decode('utf-8'))
        possibleprojects = config(ui, 'possibleprojects')
        for proj in possibleprojects.split(_(",")):
            self.jira.add_possible_project(proj.decode('utf-8'))

    def find_bugs(self, ctx):
        '''return bugs dictionary created from commit comment.

        Extract bug info from changeset comments. Filter out any that are
        not known to jira, and any that already have a reference to
        the given changeset in their comments.
        '''
        start = 0
        hours = 0.0
        bugs = {}
        description = ctx.description()
        self.ui.debug(_("description=%s\n" % description))
        bugmatch = self.bug_re.search(description, start)
        fixmatch = self.fix_re.search(description, start)
        self.ui.debug(_("bugmatch=%s, fixmatch=%s\n" % (str(bugmatch), str(fixmatch))))

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
                bugmatch = self.bug_re.search(description, start)
                bugattribs['fix'] = False
            else:
                fixmatch = self.fix_re.search(description, start)
                bugattribs['fix'] = True

            self.ui.debug(_("groups=%s\n"%str(m.groups())))
            try:
                ids = m.group('ids')
            except IndexError:
                ids = m.group(1)

            try:
                bugattribs['hours'] = 0.0
                try:
                    hours = m.group('hours')
                except IndexError:
                    hours = m.group(2)

                hours = float(hours)
                self.ui.debug(_("hours: %f\n"%hours))
                bugattribs['hours'] = hours
            except IndexError:
                pass
            except TypeError:
                pass
            except ValueError:
                self.ui.status(_("%s: invalid hours\n") % m.group(_('hours')))

            self.ui.debug(_("ids=%s\n" % str(ids)))

            bugs[ids] = bugattribs
        return bugs

    def getcomment(self, lines, bugid):
        comment = ''
        found = False
        end = False

        for line in lines:
            self.ui.debug(_('search in line %s\n' % line))
            start = 0
            # let's assume we use a template where at the end the changeset is put,after some ---
            if end or line == '------':
                if not end:
                    comment += "\n\n"
                comment += line + "\n"
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
                    comment = line
                    found = True

        return comment

    def update(self, bug, ctx):
        '''update jira bug with reference to changeset.'''
        self.ui.debug(_('\n-------------------\nupdate\n'))
        bugid, bugattribs = bug

        def webroot(root):
            '''strip leading prefix of repo root and turn into
            url-safe path.'''
            count = int(config(self.ui, 'strip'))
            root = util.pconvert(root)
            while count > 0:
                c = root.find(_('/'))
                if c == -1:
                    break
                root = root[c + 1:]
                count -= 1
            return root

        mapfile = None
        tmpl = config(self.ui, 'template')
        if not tmpl:
            mapfile = config(self.ui, 'style')
        if not mapfile and not tmpl:
            tmpl = _(
                '{desc|escape}\n\n'
                '------\n'
                'Author : {author}\n'
                'Changeset : {hgweb}/{webroot}/rev/{node|short}\n'
                'Branch : {branch}')

        self.ui.debug(_('bug=%s\n'%str(bug)))

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
        comment = self.getcomment(lines, bugid)

        self.ui.debug(_('bug\n  - comment: %s\n' % comment))
        self.ui.debug(_('  - fix: %s\n' % str(bugattribs['fix'])))
        self.ui.debug(_('  - hours: %s\n' % str(bugattribs['hours'])))

        try:
            # bugid and comment are binary, we need to decode to convert to str, jira updater only deals with str
            if bugattribs['fix']:
                self.jira.resolve_issue(bugid.decode('utf-8'), comment.decode('utf-8'), bugattribs['hours'])
            else:
                self.jira.update_issue(bugid.decode('utf-8'), comment.decode('utf-8'), bugattribs['hours'])

            self.ui.status(_('Issue %s : Updated\n'%(bugid.decode('utf-8'))))
        except RuntimeError as e:
            self.ui.warn(_("Issue %s : %s\n"%(bugid.decode('utf-8'), str(e))))
        except Exception as e:
            print("Exception:" + str(type(e))+" "+str(e))
            print('-' * 60)
            traceback.print_exc(file=sys.stdout)
            print('-' * 60)


def hook(ui, repo, hooktype, node=None, **kwargs):
    '''add comment to jira for each changeset that refers to a
    jira bug id. only add a comment once per bug, so same change
    seen multiple times does not fill bug with duplicate data.'''

    # GF : do not call jira hook when repository is cloned by TeamCity
    if str(repo.root).find("TeamCity") > 0 or str(repo.root).find("usr/local/backup") > 0:
        print('Not calling jira hook, repo is "' + repo.root + '"')
        return

    configitems.loadconfigtable(ui, "", configtable)

    if node is None:
        raise error.Abort(_('hook type %s does not pass a changeset id') % hooktype)
    try:
        ui.debug(_('\n\n----------------------\nProcessing ctx %s\n' % str(repo[node])))
        ja = jiraaccess(ui, repo)
        ctx = repo[node]

        bugs = ja.find_bugs(ctx)
        ui.debug(_('Found bugs %s\n' % str(bugs)))

        if bugs:
            for bug in bugs.items():
                ja.update(bug, ctx)

    except Exception as e:
        raise error.Abort(_('jira error: %s' % str(e)))
        pass