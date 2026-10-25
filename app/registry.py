# Agent definitions are capabilities; they are not continuously running processes.
NAMES = [
('A01','CEO / Strategy'),('A02','COO / Operations'),('A03','Project Manager'),
('A04','Market Research'),('A05','Competitor Analysis'),('A06','Brand Positioning'),
('A07','Conversion Psychology'),('A08','Creative Director'),('A09','Social Copywriter'),
('A10','Short-Video Director'),('A11','Visual Designer'),('A12','SEO / GEO / AEO'),
('A13','Social Operations'),('A14','Paid Ads Manager'),('A15','Growth Experiments'),
('A16','Data Analytics'),('A17','B2B Prospecting'),('A18','Sales'),
('A19','CRM / Lead Nurturing'),('A20','Customer Success'),('A21','Quality Assurance'),
('A22','Policy / Compliance'),('A23','Finance / Token Manager'),('A24','Red Team')]
AGENTS={agent_id:{'id':agent_id,'name':name,'status':'REGISTERED_NOT_EXECUTING'} for agent_id,name in NAMES}
AGENTS['A09']['executor'] = 'THREADS_MOCK_ONLY'
AGENTS['A01']['rule_role'] = 'DETERMINISTIC_ROUTER'
AGENTS['A21']['rule_role'] = 'RULE_QA'
AGENTS['A23']['rule_role'] = 'EXISTING_LEDGER'
