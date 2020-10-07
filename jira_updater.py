from atlassian import Jira

class JiraUpdater:
    def __init__(self, user_email, user_apikey, server):
        self.jira = Jira(server, username=user_email, password=user_apikey)
        self.possible_projects = []

    def add_possible_project(self, project):
        self.possible_projects.append(project)

    def verify_project(self, issue_id):
        res = self.jira.get_issue(issue_id, 'project')
        project_key = res['fields']['project']['key']
        if not project_key in self.possible_projects:
            raise RuntimeError("Issue %s not in possible projects %s" % (str(issue_id), str(self.possible_projects)))

    def resolve_issue(self, issue_id, comment):
        # 'Ready', 'On Hold', 'In Progress', 'Done'
        self.jira.set_issue_status(issue_id, 'Done')
        self.jira.issue_add_comment(issue_id, comment)

    def update_issue(self, issue_id, comment):
        self.jira.issue_add_comment(issue_id, comment)
