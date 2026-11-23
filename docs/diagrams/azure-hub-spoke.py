# Example: hub-spoke in Azure with internet egress through Azure Firewall.
#   bin/diagram draw docs/diagrams/azure-hub-spoke.py
#
# Layout (skill rules, inspired by archify):
#   - grid: col= and row= on every node; graphviz places any node without them
#   - main path on row 1, left to right (rol="principal")
#   - whatever hangs off a node goes right below it (key vault under sql, firewall under appgw)
#   - egress through the firewall flows backwards: rol="back"
#   - the second access (VPN from the office) enters on another row
from diagrams import Cluster, Diagram, Edge
from diagrams.azure.compute import AKS, VM
from diagrams.azure.database import SQLDatabases
from diagrams.azure.network import ApplicationGateway, Firewall, VirtualNetworkGateways
from diagrams.azure.security import KeyVaults
from diagrams.generic.network import Router
from diagrams.onprem.network import Internet

with Diagram('Hub-spoke in Azure', direction='LR'):
    internet = Internet('Internet', col=0, row=1)
    office = Router('Office', col=0, row=3)

    with Cluster('vnet-hub 10.0.0.0/16'):
        agw = ApplicationGateway('appgw + WAF', col=1, row=1)
        fw = Firewall('azfw', col=1, row=2)
        vpn = VirtualNetworkGateways('vpn-gw', col=1, row=3)

    with Cluster('vnet-aks 10.1.0.0/16'):
        aks = AKS('aks-prod', col=2, row=1)
        jump = VM('jumpbox', col=2, row=3)

    with Cluster('vnet-data 10.2.0.0/16'):
        sql = SQLDatabases('sql\nprivate endpoint', col=3, row=1)
        kv = KeyVaults('key vault', col=3, row=2)

    # main path: a user request
    internet >> Edge(label='HTTPS 443', rol='principal') >> agw
    agw >> Edge(rol='principal') >> aks
    aks >> Edge(label='1433', rol='principal') >> sql

    # branch: secrets
    aks >> Edge(label='secrets', style='dotted') >> kv

    # internet egress forced through the firewall (UDR 0.0.0.0/0)
    aks >> Edge(label='UDR 0/0', rol='back') >> fw
    fw >> Edge(rol='back') >> internet

    # administration from the office
    office >> Edge(label='IPsec', style='dashed') >> vpn
    vpn >> Edge(label='SSH') >> jump
