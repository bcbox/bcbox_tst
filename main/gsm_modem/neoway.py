from main import comm
from machine import Pin
from uasyncio import sleep
from time import sleep as wait
from gc import collect

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


class Neoway:

    def __init__(self, apn: str, client_id: str, username: str, password: str, host: str, main_topic_name: str,
                 port: int, cmd_topic_name: str, status_topic_name: str, debug: bool = False):
        self.comm_interface = comm.Interface(57600)
        self.apn: str = apn
        self.client_id: str = client_id
        self.username: str = username
        self.password: str = password
        self.main_topic_name: str = main_topic_name
        self.cmd_topic_name: str = cmd_topic_name
        self.status_topic_name: str = status_topic_name
        self.host: str = f"{host}:{port}"
        self.topic_name: str = f"{main_topic_name}/{cmd_topic_name}/#"
        self._signal_strength: int = 0
        self._pin_status: str = ""
        self._ip_address: str = ""
        self._time_str: str = ""
        self._connection_status: bool = False
        self._init_status: bool = False
        self._mqtt_status: bool = False
        self._gsm_time_init: bool = False
        self.sleep_status: bool = False
        self._power_off_status: int = 0
        self._lock_sleep_cnt: int = 0
        self._imsi: str = '0'
        self._first_connection: bool = False
        self.pwr_key_pin: Pin = Pin(14, Pin.OUT)
        self.pwr_key_pin.off()
        self.reset_pin: Pin = Pin(18, Pin.OUT)
        self.reset_pin.off()
        self.debug: bool = debug
        self._gsm_status: int = GSM_OFF
        self.time_source: str = "time.windows.com"
        self.sim_user: str = "easy"
        self.sim_pwd: str = "connect"
        self._client_id_cnt: int = 0
        self.reset_gsm_modem()
        collect()

    async def get_signal_strength(self) -> None:
        variable: str = (await self._check_msg("AT+CSQ", 'CSQ: ', extract_data=True)).split(",")[0]
        if variable.isdigit():
            self._signal_strength = self._dbm_to_percent(int(variable))
        collect()

    async def init(self) -> None:
        self.sleep_status = False

        response: bytes = await self.comm_interface.write("AT\r\n", debug=self.debug)
        if "OK" in response.decode('utf-8'):
            await self.comm_interface.write("AT+CGATT=0\r\n", debug=self.debug)
            await self.comm_interface.write("AT+XIIC=0\r\n", debug=self.debug, sleep=150000)
            await self.comm_interface.write("AT+CFUN=0\r\n", debug=self.debug, sleep=120000)
            await sleep(2)
            await self.comm_interface.write("AT+IPR=57600\r\n", debug=self.debug)
            await self.comm_interface.write("AT+CFUN=1\r\n", debug=self.debug, sleep=120000)
            await sleep(5)
            response = await self.comm_interface.write("AT+CPIN?\r\n", debug=self.debug)
            if "READY" not in response.decode('utf-8'):
                self._gsm_status = SIM_CARD_NOT_READY
                print("SIM card not ready")
                return
            await self.comm_interface.write("AT+CREG=2\r\n", debug=self.debug)
            await self.comm_interface.write("AT+LEDMODE=1\r\n", debug=self.debug)
            await self.comm_interface.write("AT+NVSETBAND=8,1,3,5,8,19,20,26,28\r\n", debug=self.debug)
            self._imsi: str = (await self._check_msg('AT+CIMI', 'CIMI: ', extract_data=True, timeout=5000)).split("\r")[0]
            await self.comm_interface.write(r'AT+CGDCONT=1,"IP","' + self.apn + '"\r\n', debug=self.debug, sleep=2000)
            # await self.comm_interface.write(r'AT+XGAUTH=1,1,"' + self.sim_user + '","' + self.sim_pwd + '"\r\n', debug=self.debug)
            variable: str = (await self._check_msg("AT+NEONBIOTCFG?", 'NEONBIOTCFG: ', extract_data=True)).split("\r")[0]
            if "1,0,0,0" not in variable:
                if (await self._check_msg("AT+NEONBIOTCFG=1,0,0,0", 'OK')) == "OK":
                    self._gsm_status = INIT_SUCCESSFUL
                    self._init_status = True
            else:
                self._gsm_status = INIT_SUCCESSFUL
                self._init_status = True

    async def check_connection(self) -> None:
        self._gsm_status = INIT_SUCCESSFUL
        await self.get_signal_strength()
        if self._signal_strength == 0:
            print("****** Not register or low gsm signal! ******")
            return
        variable: str = (await self._check_msg("AT+CGATT?", 'CGATT: ', extract_data=True)).split("\r")[0]
        if variable.isdigit() and int(variable) == 1:
            self._gsm_status = CONNECT_TO_PS
            if self._first_connection:
                if (await self._check_msg("AT+XIIC=1", 'OK', timeout=150000)) != "OK":
                    return
            response: str = (await self._check_msg("AT+XIIC?", 'XIIC: ', extract_data=True)).split("\r")[0]
            status: str = response.split(",")[0]
            self._ip_address = response.split(",")[1]
            if int(status) == 1:
                await sleep(5)
                if not self.gsm_time_init:
                    await self.get_actual_time()
                self._first_connection = True
                self._connection_status = True
                self._gsm_status = SET_UP_PPP
            else:
                self._connection_status = False
        elif self._first_connection:
            await self.comm_interface.write("AT+CGATT=1", sleep=150000, debug=self.debug)

    async def mqtt_init(self) -> None:
        self._gsm_status = SET_UP_PPP
        self._client_id_cnt += 1
        await self.get_signal_strength()
        if self._signal_strength == 0:
            print("****** Low gsm signal! ******")
            return
        if await self._check_msg("AT+MQTTMODE=1", 'OK') != "OK":
            print("****** AT+MQTTMODE ERROR! ******")
            return
        if await self._check_msg(r'AT+MQTTCONNPARAM="' + self.client_id + f"{self._client_id_cnt}" + '","' + self.username + '","' + self.password + '"', 'OK') != "OK":
            print("****** AT+MQTTCONNPARAM ERROR! ******")
            return
        if await self._check_msg(r'AT+MQTTCONN="' + self.host + '",0,60', 'OK', timeout=120000) != "OK":
            print("****** AT+MQTTCONN ERROR! ******")
            self._connection_status = False
            return
        if await self._check_msg(r'AT+MQTTSUB="' + self.topic_name + '",1', 'OK', timeout=60000) != "OK":
            return
        self._mqtt_status = True
        self._gsm_status = MQTT_CONNECT

    async def get_actual_time(self) -> None:
        await self.comm_interface.write(r'AT+UPDATETIME=1,"' + self.time_source + '",10,"0"\r\n', debug=self.debug, sleep=30000)
        await sleep(30)
        self.comm_interface.read()
        response: str = await self._check_msg("AT+CCLK?", 'CCLK: ', extract_data=True)
        self._time_str = response.split("\r")[0]
        self._gsm_time_init = True

    async def check_mqtt_connection(self) -> int:
        """
        0: the MQTT connection is closed.
        1: the MQTT connection is established.
        2: The device is reconnecting to the MQTT server.
        3: The device starts to reconnect to the MQTT server.
        4: The device fails to reconnect to the MQTT server.
        """
        response: str = await self._check_msg("AT+MQTTSTATE?", 'MQTTSTATE:', extract_data=True)
        decode_response: str = response.split("\r")[0]
        if decode_response in {'1', '2'}:
            self._connection_status = True
            self._mqtt_status = True
            self._gsm_status = MQTT_CONNECT
            if decode_response == '2':
                self._gsm_status = MQTT_RECONNECT
            return int(decode_response)
        else:
            self._gsm_status = MQTT_DISCONNECT

        self._mqtt_status = decode_response in {'1', '2', '3', '4'}
        return int(decode_response)

    def read_mqtt_data(self) -> str:
        res: str = self.comm_interface.read(debug=self.debug).decode('utf-8')
        if "MQTTSUB" in res:
            variable: str = self._check_mqtt_msg(res, 'MQTTSUB:0,', extract_data=True).split("\r")[0]
            var = variable.split(",")[2:]
            mqtt_msg = ",".join(var)
            return mqtt_msg
        elif "MQTTDISCONNED" in res:
            return "MQTTDISCONNED"
        return ""

    async def _check_msg(self, cmd: str, substring: str, extract_data: bool = False, timeout: int = 500) -> str:
        received_msg: bytes = await self.comm_interface.write(f"{cmd}\r\n", sleep=timeout, debug=self.debug)
        decode_msg: str = received_msg.decode('utf-8')
        if substring in decode_msg:
            if extract_data:
                return decode_msg.split(substring)[1]
            else:
                return substring
        else:
            return "NOK\r\n"

    @staticmethod
    def _check_mqtt_msg(msg: str, substring: str, extract_data: bool = False) -> str:
        if substring in msg:
            if extract_data:
                return msg.split(substring)[1]
            else:
                return substring
        else:
            return "NOK"

    async def power_off(self) -> None:
        self._power_off_status += 1
        if self._power_off_status <= 3:
            print("Power off neoway module!")
            self._gsm_status = GSM_OFF
            await self.comm_interface.write("AT+CPWROFF\r\n", debug=self.debug)

    def reset_gsm_modem(self) -> None:
        print("Reset neoway module!")
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
        await self.comm_interface.write(r'AT+MQTTUNSUB="' + self.topic_name + '"\r\n', debug=self.debug, sleep=30000)
        await self.comm_interface.write("AT+MQTTDISCONN\r\n", debug=self.debug, sleep=30000)
        self._mqtt_status = False

    async def mqtt_publish(self, report) -> str:
        res: str = (await self.comm_interface.write(r'AT+MQTTPUB=0,1,"' + self.main_topic_name + '/' + self.status_topic_name + '","' + report + '"\r\n', debug=self.debug, sleep=60000)).decode('utf-8')
        if "MQTTSUB" in res:
            variable: str = self._check_mqtt_msg(res, 'MQTTSUB:0,', extract_data=True).split("\r")[0]
            var = variable.split(",")[2:]
            mqtt_msg = ",".join(var)
            return mqtt_msg
        return ""

    def get_time(self):
        date_part, time_part = self._time_str.split(',')
        time_part = time_part.split('+')[0]
        date_part = date_part.replace('\"', '')
        year, month, day = map(int, date_part.strip().split('/'))
        hours, minutes, seconds = map(int, time_part.strip().split(':')[0:3])
        year += 2000
        return year, month, day, hours, minutes, seconds

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
    def pin_status(self) -> str:
        return self._pin_status

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
        return "Unknown"

    @property
    def network_type(self) -> str:
        return "Unknown"
