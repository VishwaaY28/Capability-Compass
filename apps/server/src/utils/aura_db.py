from neo4j import GraphDatabase

# URI examples: "neo4j://localhost", "neo4j+s://xxx.databases.neo4j.io"
URI = "neo4j://b814b647.databases.neo4j.io"
AUTH = ("neo4j", "cV_ZVZ5Z0rCzg7QOIklJ8JFYvzBtRHapT_id3eDG2Dw")

with GraphDatabase.driver(URI, auth=AUTH) as driver:
    driver.verify_connectivity()