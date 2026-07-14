from softether_gui.parser import parse_account_list, parse_account_profile, parse_nic_list


ACCOUNT_LIST = """
VPN Client>AccountList
AccountList command - Get List of VPN Connection Settings
Item                        |Value
----------------------------+------------------------------------------------------------
VPN Connection Setting Name |workaccount
Status                      |Connected
VPN Server Hostname         |vpn.example.com:443 (Direct TCP/IP Connection)
Virtual Hub                 |DEFAULT
Virtual Network Adapter Name|worknic
----------------------------+------------------------------------------------------------
VPN Connection Setting Name |backup
Status                      |Offline
VPN Server Hostname         |backup.example.com:5555 (Direct TCP/IP Connection)
Virtual Hub                 |PUBLIC
Virtual Network Adapter Name|backupnic
The command completed successfully.
"""

NIC_LIST = """
Item                        |Value
----------------------------+-----------------------------------
Virtual Network Adapter Name|worknic
Status                      |Enabled
MAC Address                 |00AC5B6D236F
Version                     |Version 4.44 Build 9807 (English)
"""

ACCOUNT_GET = """
Item                                                 |Value
-----------------------------------------------------+--------------------------------
VPN Connection Setting Name                          |workaccount
Destination VPN Server Host Name                     |vpn.example.com
Destination VPN Server Port Number                   |443
Destination VPN Server Virtual Hub Name              |DEFAULT
Proxy Server Type                                    |Direct TCP/IP Connection
Verify Server Certificate                            |Disable
Device Name Used for Connection                      |worknic
Authentication Type                                  |Standard Password Authentication
User Name                                            |keith
Number of TCP Connections to Use in VPN Communication|8
Interval between Establishing Each TCP Connection    |1
Connection Life of Each TCP Connection               |Infinite
Use Half Duplex Mode                                 |Disable
Encryption by SSL                                    |Enable
Data Compression                                     |Disable
Connect by Bridge / Router Mode                      |Disable
Connect by Monitoring Mode                           |Disable
No Adjustment for Routing Table                      |Disable
Do not Use QoS Control Function                      |Disable
"""


def test_account_list():
    accounts = parse_account_list(ACCOUNT_LIST)
    assert len(accounts) == 2
    assert accounts[0].name == "workaccount"
    assert accounts[0].nic == "worknic"
    assert accounts[0].is_connected
    assert accounts[1].hub == "PUBLIC"


def test_nic_list():
    nics = parse_nic_list(NIC_LIST)
    assert nics[0].name == "worknic"
    assert nics[0].mac == "00AC5B6D236F"


def test_account_get():
    profile = parse_account_profile("workaccount", ACCOUNT_GET)
    assert profile.server == "vpn.example.com"
    assert profile.port == 443
    assert profile.username == "keith"
    assert profile.max_tcp == 8
    assert profile.encrypt is True
