#!/usr/bin/env python3
import argparse
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import Node, OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel


class LinuxRouter(Node):
    """Node Linux đóng vai trò gateway/router có bật IP forwarding."""

    def config(self, **params):
        super().config(**params)
        self.cmd("sysctl -w net.ipv4.ip_forward=1")

    def terminate(self):
        self.cmd("sysctl -w net.ipv4.ip_forward=0")
        super().terminate()


class IoTWanTopo(Topo):
    """Topology: h1..hN -> s1 -> hg -> r1 -> server."""

    def build(self, n_sensors=20):
        if not (10 <= n_sensors <= 100):
            raise ValueError("N phai nam trong khoang tu 10 den 100")

        s1 = self.addSwitch("s1", cls=OVSKernelSwitch, failMode="standalone")
        hg = self.addHost("hg", cls=LinuxRouter, ip="10.0.1.1/24")
        r1 = self.addHost("r1", cls=LinuxRouter, ip="10.0.2.2/24")
        server = self.addHost("server", ip="10.0.3.2/24", defaultRoute="via 10.0.3.1")

        # Cảm biến h1..hN nối vào switch s1
        for i in range(1, n_sensors + 1):
            h = self.addHost(
                f"h{i}",
                ip=f"10.0.1.{i + 1}/24",
                defaultRoute="via 10.0.1.1",
            )
            self.addLink(h, s1)

        # s1 -> hg
        self.addLink(
            s1,
            hg,
            intfName2="hg-eth0",
            params2={"ip": "10.0.1.1/24"},
        )

        # hg <-> r1
        self.addLink(
            hg,
            r1,
            intfName1="hg-eth1",
            params1={"ip": "10.0.2.1/24"},
            intfName2="r1-eth0",
            params2={"ip": "10.0.2.2/24"},
        )

        # r1 <-> server
        self.addLink(
            r1,
            server,
            intfName1="r1-eth1",
            params1={"ip": "10.0.3.1/24"},
        )


def run(n_sensors):
    topo = IoTWanTopo(n_sensors=n_sensors)
    net = Mininet(topo=topo, controller=None, autoSetMacs=True)
    net.start()

    hg = net.get("hg")
    r1 = net.get("r1")

    # Tuyến tĩnh hai chiều giữa các subnet
    hg.cmd("ip route add 10.0.3.0/24 via 10.0.2.2")
    r1.cmd("ip route add 10.0.1.0/24 via 10.0.2.1")

    CLI(net)
    net.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-n",
        "--sensors",
        type=int,
        default=20,
        help="So luong cam bien (tu 10 den 100)",
    )
    args = parser.parse_args()
    setLogLevel("info")
    run(args.sensors)
