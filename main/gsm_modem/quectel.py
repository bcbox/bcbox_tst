from main.comm import Interface
from machine import Pin
from asyncio import sleep
from ulogging import getLogger, ERROR, DEBUG, INFO
from time import sleep as wait
from gc import collect
import re


collect()

GSM_OFF: int = 0
SIM_CARD_NOT_READY: int = 1
INIT_SUCCESSFUL: int = 2
CONNECT_TO_PS: int = 3
SET_UP_PPP: int = 4
MQTT_DISCONNECT: int = 5
MQTT_CONNECT: int = 6
MQTT_RECONNECT: int = 7
LOW_SIGNAL: int = 8

QUECTEL_MQTT_INITIALIZING: int = 1
QUECTEL_MQTT_CONNECTING: int = 2
QUECTEL_MQTT_CONNECTED: int = 3
QUECTEL_MQTT_DISCONNECTING: int = 4

CID: int = 1

NETWORK_TYPE: dict = {0: "GSM", 8: "eMTC", 9: "NB-IoT"}


class Quectel:

    def __init__(self, apn: str, client_id: str, username: str, password: str, host: str, main_topic_name: str,
                 port: int, cmd_topic_name: str, status_topic_name: str, debug: bool = False):
        self.comm_interface = Interface(115200)
        self.apn: str = apn
        self.client_id: str = client_id
        self.username: str = username
        self.password: str = password
        self.main_topic_name: str = main_topic_name
        self.cmd_topic_name: str = cmd_topic_name
        self.status_topic_name: str = status_topic_name
        self.host: str = host
        self.port: int = port
        self.topic_name: str = f"{main_topic_name}/{cmd_topic_name}/#"
        self._signal_strength: int = 0
        self._ip_address: str = ""
        self._time_str: str = ""
        self._connection_status: bool = False
        self._init_status: bool = False
        self._mqtt_status: bool = False
        self._gsm_time_init: bool = False
        self._lock_sleep_cnt: int = 0
        self._imsi: str = '0'
        self._first_connection: bool = True
        self._gsm_status: int = GSM_OFF
        self._client_id_cnt: int = 0
        self._operator: str = ""
        self._network_type: int = 0
        self.pwr_key_pin: Pin = Pin(14, Pin.OUT)
        self.pwr_key_pin.off()
        self.reset_pin: Pin = Pin(18, Pin.OUT)
        self.reset_pin.off()

        self.logger = getLogger(__name__)
        self.logger.setLevel(INFO)

        self.reset_gsm_modem()
        collect()

    async def get_signal_strength(self) -> str:
        response: str = (await self._check_msg("AT+CSQ", 'CSQ: ', extract_data=True)).split(",")[0]
        match = re.search(r'\+QMTRECV:.*', response)
        qmtrecv_message: str = ""
        if match:
            qmtrecv_message = match.group(0)
        if response.isdigit():
            self._signal_strength = self._dbm_to_percent(int(response))
        collect()
        return qmtrecv_message

    async def init(self) -> None:
        response: bytes = await self.comm_interface.write("AT\r\n")
        if "OK" in response.decode('utf-8'):
            await self.comm_interface.write("AT+CFUN=0\r\n", sleep=15000)
            await self.comm_interface.write(r'AT+CGDCONT=' + f"{CID}" + ',"IP","' + self.apn + '"\r\n', sleep=1000)
            await self.comm_interface.write("AT+CFUN=1\r\n", sleep=15000)
            await sleep(2)

            response = await self.comm_interface.write("AT+CPIN?\r\n")
            while "READY" not in response.decode('utf-8'):
                self._gsm_status = SIM_CARD_NOT_READY
                self.logger.warning("SIM card not ready")
                await sleep(1)
                response = await self.comm_interface.write("AT+CPIN?\r\n")

            self._imsi: str = (await self._check_msg('AT+CIMI', 'AT+CIMI\r\r\n', extract_data=True, timeout=1000)).split("\r")[0]
            self._gsm_status = INIT_SUCCESSFUL
            self._init_status = True

    async def check_connection(self) -> None:
        self._gsm_status = INIT_SUCCESSFUL
        await self.get_signal_strength()
        if self.signal_strength == 0:
            self.logger.warning("Not register or low gsm signal!")
            return
        await self.get_operator_status()
        await self.comm_interface.write("AT+CGATT=1\r\n", sleep=150000)
        mobile_data: str = (await self._check_msg("AT+CGATT?", 'CGATT: ', extract_data=True)).split("\r")[0]
        if mobile_data.isdigit() and int(mobile_data) == 1:
            self._gsm_status = CONNECT_TO_PS
            response: bytes = await self.comm_interface.write("AT+CGPADDR=1\r\n")
            response_str = response.decode('utf-8')
            match = re.search(r'\+CGPADDR: \d+,([\d\.]+)', response_str)
            if match:
                self._ip_address = match.group(1)
                self.logger.info(f"IP ADDRESS: {self._ip_address}")
            if not self.gsm_time_init:
                await self.set_time()
            self._connection_status = True
            self._gsm_status = SET_UP_PPP
        else:
            self._connection_status = False

    async def mqtt_init(self) -> None:
        self._gsm_status = SET_UP_PPP
        await self.get_signal_strength()
        if self.signal_strength == 0:
            self.logger.warning("Low gsm signal!")
            return
        if not self._first_connection:
            self._first_connection = True
            await self.mqtt_disconnect()
        if await self._check_msg(cmd=r'AT+QMTCFG="ssl",0,1,0', substring='OK') != "OK":
            self.logger.info("****** AT+MQTTMODE ERROR! ******")
            return
        if await self._check_msg(cmd=r'AT+QMTCFG="keepalive",0,60', substring='OK') != "OK":
            self.logger.info("****** AT+MQTTMODE ERROR! ******")
            return
        if await self._check_msg(cmd=r'AT+QMTOPEN=0,"' + self.host + '",' + f"{self.port}", substring='QMTOPEN: 0,', extract_data=True, result="QMTOPEN:", timeout=100000) != "0":
            await self.deactivate_pdp()
            await self.activate_pdp()
            self.logger.info("****** AT+MQTTCONNPARAM ERROR! ******")
            return
        if await self._check_msg(cmd=r'AT+QMTCONN=0,"' + self.client_id + '","' + self.username + '","' + self.password + '"', substring='QMTCONN: 0,', extract_data=True, result="QMTCONN:", timeout=100000) != "0,0":
            self.logger.info("****** AT+MQTTCONN ERROR! ******")
            self._connection_status = False
            return
        if await self._check_msg(cmd=r'AT+QMTSUB=0,1,"' + self.topic_name + '",1', substring='QMTSUB: 0,1,', extract_data=True, result="QMTSUB:", timeout=100000) != "0,1":
            return
        self._mqtt_status = True
        self._gsm_status = MQTT_CONNECT

    async def set_time(self) -> None:
        response = await self.comm_interface.write('AT+QLTS=1\r\n')
        self._time_str = response.decode('utf-8').split('"')[1]
        self._gsm_time_init = True

    def read_mqtt_data(self) -> str:
        res: str = self.comm_interface.read().decode('utf-8')
        qmtrecv_match = re.search(r'QMTRECV:.*,"([^"]+)"', res)
        if qmtrecv_match:
            mqtt_msg = qmtrecv_match.group(1)
            return mqtt_msg

        qmtstat_match = re.search(r'QMTSTAT:\s*(\d+),\s*(\d+)', res)
        if qmtstat_match:
            client_idx = int(qmtstat_match.group(1))
            err_code = int(qmtstat_match.group(2))
            self.handle_mqtt_status(client_idx, err_code)

        return ""

    async def _check_msg(self, cmd: str, substring: str, extract_data: bool = False, timeout: int = 500, result: str = "OK\r\n") -> str:
        received_msg: bytes = await self.comm_interface.write(f"{cmd}\r\n", sleep=timeout, result=result)
        decode_msg: str = received_msg.decode('utf-8')
        if substring in decode_msg:
            if extract_data:
                result = decode_msg.split(substring)[1]
                return result.split("\r")[0]
            else:
                return substring
        else:
            return "NOK\r\n"

    async def check_mqtt_connection(self) -> tuple[int, str]:
        """
        0: the MQTT connection is closed.
        1: the MQTT connection is established.
        2: The device is reconnecting to the MQTT server.
        3: The device starts to reconnect to the MQTT server.
        4: The device fails to reconnect to the MQTT server.
        """
        response: str = (await self.comm_interface.write('AT+QMTCONN?\r\n')).decode('utf-8')
        match = re.search(r'\+QMTRECV:.*', response)
        qmtrecv_message: str = ""
        if match:
            qmtrecv_message = match.group(0)

        lines = response.split('\r\n')
        state = None
        for line in lines:
            if line.startswith('+QMTCONN:'):
                parts = line.split(',')
                if len(parts) >= 2:
                    state = parts[1].strip()
                    break
        if state is not None:
            state_int = int(state)
            if state_int == QUECTEL_MQTT_INITIALIZING or state_int == QUECTEL_MQTT_CONNECTING:
                self._gsm_status = MQTT_RECONNECT
                return 2, qmtrecv_message
            elif state_int == QUECTEL_MQTT_CONNECTED:
                self._gsm_status = MQTT_CONNECT
                return 1, qmtrecv_message
            else:
                self._mqtt_status = False
                self._connection_status = False
                self._gsm_status = MQTT_DISCONNECT
                return 0, qmtrecv_message

    def wake_up(self) -> None:
        self.logger.info("Wake up quectel module!")
        self._lock_sleep_cnt = 0
        self.pwr_key_pin.on()
        collect()

    async def power_off(self) -> None:
        self.logger.info("Power off quectel module!")
        self._gsm_status = GSM_OFF
        await self.comm_interface.write("AT+QPOWD=1\r\n")

    def reset_gsm_modem(self) -> None:
        self.logger.info("Reset quectel module!")
        self._gsm_status = False
        self._init_status = False
        self._connection_status = False
        self._mqtt_status = False
        self.reset_pin.on()
        wait(3)
        self.reset_pin.off()
        wait(3)
        collect()

    async def mqtt_disconnect(self) -> None:
        await self._check_msg(cmd=r'AT+QMTUNS=0,1,"' + self.topic_name + '"\r\n',  substring='QMTUNS: ', extract_data=True, result="QMTUNS:", timeout=100000)
        await self._check_msg(cmd="AT+QMTDISC=0\r\n",  substring='QMTDISC: ', extract_data=True, result="QMTDISC:", timeout=100000)
        await self._check_msg(cmd="AT+QMTCLOSE=0\r\n",  substring='QMTCLOSE: ', extract_data=True, result="QMTCLOSE:", timeout=100000)
        self._mqtt_status = False

    async def mqtt_publish(self, report) -> str:
        response: str = (await self.comm_interface.write(r'AT+QMTPUBEX=0,1,1,0,"' + self.main_topic_name + '/' + self.status_topic_name + '","' + report + '"\r\n', sleep=60000)).decode('utf-8')
        match = re.search(r'\+QMTRECV:.*', response)
        if match:
            qmtrecv_message = match.group(0)
            return qmtrecv_message
        return ""

    def get_time(self) -> tuple[str, str, str, str, str, str]:
        date_part, time_part = self._time_str.split(',')[:2]
        time_part = time_part.split('+')[0]
        date_part = date_part.replace('"', '')
        year, month, day = map(int, date_part.strip().split('/'))
        hours, minutes, seconds = map(int, time_part.strip().split(':')[0:3])
        return year, month, day, hours, minutes, seconds

    def handle_mqtt_status(self, client_idx: int, err_code: int) -> None:
        if 0 < err_code <= 7:
            self._mqtt_status = False
            self._connection_status = False

        if err_code == 1:
            self.logger.info(f"MQTT client {client_idx}: Connection closed or reset by peer. Reopening connection...")

        elif err_code == 2:
            self.logger.info(f"MQTT client {client_idx}: PINGREQ timeout. Deactivating and reactivating PDP...")
            self.deactivate_pdp()
            self.activate_pdp()

        elif err_code == 3:
            self.logger.info(f"MQTT client {client_idx}: CONNECT packet timeout. Rechecking credentials and reopening connection...")

        elif err_code == 4:
            self.logger.info(f"MQTT client {client_idx}: CONNACK packet timeout. Rechecking credentials and reopening connection...")

        elif err_code == 5:
            self.logger.info(f"MQTT client {client_idx}: Server closed connection, normal process.")

        elif err_code == 6:
            self.logger.info(f"MQTT client {client_idx}: Client closed connection due to packet sending failure. Trying to reopen connection...")

        elif err_code == 7:
            self.logger.info(f"MQTT client {client_idx}: Link is not alive or server is unavailable. Checking link and server status...")

        else:
            self.logger.info(f"MQTT client {client_idx}: Unknown error code {err_code}.")

    async def deactivate_pdp(self):
        """
        Sends an AT command to deactivate the PDP context.
        """
        try:
            response: bytes = await self.comm_interface.write(f"AT+CGATT=0\r\n", sleep=150000, result="CGATT: ")
            self.logger.info("Deactivating PDP: ", response)
        except Exception as e:
            self.logger.error(f"Error deactivating PDP context: {str(e)}")

    async def activate_pdp(self):
        """
        Sends an AT command to activate the PDP context with necessary parameters.
        """
        try:
            response: bytes = await self.comm_interface.write(f"AT+CGATT=1\r\n", sleep=150000, result="CGATT: ")
            self.logger.info("Activating PDP: ", response)
        except Exception as e:
            self.logger.error(f"Error activating PDP context: {str(e)}")

    async def get_operator_status(self) -> str:
        response: bytes = await self.comm_interface.write("AT+COPS?\r\n")
        response_str: str = response.decode("utf-8")
        match = re.search(r'\+COPS: \d+,\d+,"([^"]+)",(\d+)', response_str)
        if match:
            self._operator = match.group(1)
            self._network_type = int(match.group(2))
        mqtrevc_match = re.search(r'\+QMTRECV:.*', response_str)
        qmtrecv_message: str = ""
        if mqtrevc_match:
            qmtrecv_message = match.group(0)
        collect()
        return qmtrecv_message

    @staticmethod
    def _dbm_to_percent(dbm) -> int:
        if dbm < 4 or dbm == 99:
            return 0
        elif dbm >= 28:
            return 100
        else:
            return int(((dbm - 3) / (28 - 3)) * 100)

    @property
    def signal_strength(self) -> int:
        return self._signal_strength

    @property
    def ip_address(self) -> str:
        return self._ip_address

    @property
    def connection_status(self) -> bool:
        return self._connection_status

    @property
    def init_status(self) -> bool:
        return self._init_status

    @property
    def mqtt_status(self) -> bool:
        return self._mqtt_status

    @property
    def gsm_time_init(self) -> bool:
        return self._gsm_time_init

    @property
    def imsi(self) -> str:
        return self._imsi

    @property
    def gsm_status(self) -> int:
        return self._gsm_status

    @property
    def operator(self) -> str:
        return self._operator

    @property
    def network_type(self) -> str:
        if self._network_type in NETWORK_TYPE:
            return NETWORK_TYPE[self._network_type]
        return "Unknown"
