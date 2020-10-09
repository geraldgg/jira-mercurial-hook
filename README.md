## Hook for integrating with Jira

    sudo pip install atlassian-python-api
    sudo pip install brotli

This hook extension adds comments on issues in Jira when changesets
that refer to issue by Jira ID are seen. The comment is formatted using
the Mercurial template mechanism.

The bug references can optionally include an update for jira of the
hours spent working on the bug. Bugs can also be marked fixed.

Access is done via the atlassian python api (REST-API) and requires
a jira username and api key specified in the configuration. Comments
are made under the given username or the user associated with the apikey in jira.

Configuration items common to all access modes:

* jira.regexp

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

* jira.fixregexp

  Same as previous regexp, except that sjira is searched insteaod of jira

* jira.fixstatus

  The status to set a bug to when marking fixed. Default ``Accepted``.

* jira.fixresolution

  The resolution to set a bug to when marking fixed. Default ``Resolved``.

* jira.template

  Template to use when formatting comments. Overrides style if
  specified. In addition to the usual Mercurial keywords, the
  extension specifies:

  :``{bug}``:     The jira bug ID.
  
  :``{root}``:    The full pathname of the Mercurial repository.
  
  :``{webroot}``: Stripped pathname of the Mercurial repository.
  
  :``{hgweb}``:   Base URL for browsing Mercurial repositories.

  Default 
  
  ``{desc|escape}\n\n------\nAuthor : {author}\nChangeset : {hgweb}/{webroot}/rev/{node|short}\nBranch : {branch}'``

* jira.strip

  The number of path separator characters to strip from the front of
  the Mercurial repository path (``{root}`` in templates) to produce
  ``{webroot}``. For example, a repository with ``{root}``
  ``/var/local/my-project`` with a strip of 2 gives a value for
  ``{webroot}`` of ``my-project``. Default 0.

* web.baseurl

  Base URL for browsing Mercurial repositories. Referenced from
  templates as ``{hgweb}``.

* jira.url

  The base URL for the jira installation.
  Default ````.

* jira.possibleprojects

  List of possible projects in Jira, separated by a comma. If an issue id
  is in a project not in this list, it won't be updated
  example: ABCD,EFGH
  Default ````.

* jira.useremail

  The user email to use to log into jira.

* jira.apikey

  An apikey generated on the jira instance for api access.
  Using an apikey removes the need to store the user and password
  options.

Activating the extension:

In the hgrc of the repository on server :

    [extensions]
    jira =

    [hooks]
    # run jira hook on every change pulled or pushed in here
    incoming.jira = python:hgext.jira.hook (or python:/path/to/jira-mercurial_hook.py)

    [jira]
    url=https://myjira.atlassian.net/
    useremail=user@company.com
    apikey=123456798ABCDEF
    possibleprojects=ABCD,EFGH
    strip=5
    template = {desc|escape}\n\n------\nAuthor : {author}\nChangeset : {hgweb}/{webroot}/rev/{node|short}\nBranch : {branch}

