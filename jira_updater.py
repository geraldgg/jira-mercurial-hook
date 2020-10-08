import urllib3
from atlassian import Jira

class JiraUpdater:
    def __init__(self, user_email, user_apikey, server):
        self.jira = Jira(server, username=user_email, password=user_apikey, advanced_mode=True)
        self.possible_projects = []

    def add_possible_project(self, project):
        self.possible_projects.append(project)

    def verify_project(self, issue_id):
        try:
            res = self.jira.get_issue(issue_id, 'project')
        except urllib3.exceptions.MaxRetryError as e:
            raise RuntimeError(str(e))

        if res.status_code == 401:
            raise RuntimeError("Error: %s. Check your login and apikey.\n%s"%(res.reason, res.text))

        res = res.json()
        if 'errorMessages' in res:
            raise RuntimeError("Error : "+res['errorMessages'][0])

        project_key = res['fields']['project']['key']
        if not project_key in self.possible_projects:
            raise RuntimeError("Issue %s not in possible projects %s" % (str(issue_id), str(self.possible_projects)))

    def resolve_issue(self, issue_id, comment, hours):
        # 'Ready', 'On Hold', 'In Progress', 'Done'
        self.verify_project(issue_id)
        self.jira.set_issue_status(issue_id, 'Done')
        self.update_issue(issue_id, comment, hours)

    def update_issue(self, issue_id, comment, hours):
        self.verify_project(issue_id)
        self.jira.issue_add_comment(issue_id, comment)
        if hours>0.0:
            self.jira.issue_worklog(issue_id, None, hours*3600.0)

