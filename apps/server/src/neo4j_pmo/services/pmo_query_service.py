import os
from neo4j import GraphDatabase


class PmoQueryService:
    """Neo4j query service targeting the compass-pmo database."""

    def __init__(self):
        uri = os.getenv("NEO4J_URI")
        user = os.getenv("NEO4J_USERNAME")
        password = os.getenv("NEO4J_PASSWORD")
        if not uri or not user or not password:
            raise ValueError("Neo4j connection details (NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD) are not set.")
        self.database = os.getenv("NEO4J_PMO_DATABASE", "compass-pmo")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def execute_cypher(self, query: str, parameters: dict = None):
        with self.driver.session(database=self.database) as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]
