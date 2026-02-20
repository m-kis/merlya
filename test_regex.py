import re

text = "connecte toi sur 192.168.108.250 et a travers cette machine va sur 149.202.174.247 (cest phpmyadmin) analyse ce qui est sur cette machine phpmyadmin je veux connaitre les serveurs et leurs bases sur cette machine"

hosts = []
ips = re.findall(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", text)
print("ips:", ips)

host_preposition_patterns = [
    r"\b(?:on|sur|from|to|at|de)\s+([a-zA-Z][a-zA-Z0-9_.-]*)",
    r"\b(?:serveur|server|host|machine|hôte|instance)\s+([a-zA-Z][a-zA-Z0-9_.-]*)",
]
matches = []
for p in host_preposition_patterns:
    matches.extend(re.findall(p, text, re.IGNORECASE))
print("prepostions:", matches)

standalone_host_pattern = (
    r"\b([a-zA-Z][a-zA-Z0-9]*(?:[-_][a-zA-Z0-9]+)+|[a-zA-Z]+\d+[a-zA-Z0-9]*)\b"
)
print("standalone:", re.findall(standalone_host_pattern, text))
