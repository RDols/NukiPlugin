"""
<plugin key="NukiPlugin" name="Nuki Smart Lock Plugin" author="R.Dols" version="0.0.20">
    <description>
        <h2>Nuki Smart Lock 0.0.20</h2><br/>
        <h3>Notes:</h3>
        <ul style="list-style-type:square">
            <li>Still under development</li>
        </ul>
        <h3>To Do:</h3>
        <ul style="list-style-type:square">
            <li>A lot !</li>
            <li>Simple sensors and buttons</li>
            <li>keypad</li>
        </ul>
    </description>
    <params>
        <param field="Address" label="IP Address" width="200px" required="true" default="127.0.0.1"/>
        <param field="Port" label="Port" width="30px" required="true" default="8080"/>
        <param field="Mode1" label="API key" width="200px" required="true"/>
        <param field="Mode6" label="Log Level" width="100px">
            <description><h2>Debugging</h2>Select the desired level of debug messaging</description>
            <options>
                <option label="Off" value="Off"/>
                <option label="Error" value="Error" default="true" />
                <option label="Debug" value="Debug"/>
            </options>
        </param>
    </params>
</plugin>
"""
from contextlib import nullcontext
import Domoticz # type: ignore
import json
import socket
import urllib.request

# to make my linter not go crazy
Devices = {} 
Parameters = NotImplemented

class NukiPlugin:
    Bridges = {}
    Locks = {}
    ListenSocket = nullcontext
    ListenPort = 5922

    def onStart(self):
        self.SetLogLevel()
        self.Bridges[0] = { "Ip":Parameters["Address"], "Port":Parameters["Port"], "ApiKey":Parameters["Mode1"] }
        self.ListDevices()
        self.CreateCallbacks()


    def FindBridges(self):
        data = urllib.request.urlopen("https://api.nuki.io/discover/bridges").read().decode('utf-8')
        response = json.loads(data)
        if ('bridges' in response):
            for bridge in response["bridges"]:
                Domoticz.Log("bridge found : id=" + str(bridge["bridgeId"]) + " ip:" + bridge["ip"] + " port:" + str(bridge["port"]))
                self.Bridges[bridge["bridgeId"]] = { "ip":bridge["ip"], "port":bridge["port"]}


    def ListDevices(self):
        for row in self.Bridges:
            bridge = self.Bridges[row]
            url = 'http://' + bridge["Ip"] + ':' + bridge["Port"] + "/list?token=" + bridge["ApiKey"]
            data = urllib.request.urlopen(url).read().decode('utf-8')
            response = json.loads(data)
            for lockInfo in response:
                self.ProcessLockInfo(bridge, lockInfo)


    def ProcessLockInfo(self, bridge, lockInfo):
        self.CreateIfNotExists(lockInfo)

        lock = self.Locks[lockInfo["nukiId"]]
        lock["Bridge"] = bridge
        stateInfo = lockInfo["lastKnownState"]
        self.UpdateDoorInfo(lock, stateInfo["state"], stateInfo["batteryChargeState"], False)
        self.UpdateSensorInfo(lock, stateInfo["doorsensorState"], False)


    def ProcessCallbackInfo(self, callbackInfo):
        if callbackInfo["nukiId"] not in self.Locks:
            Domoticz.Log("Lock not found")
            return
        
        lock = self.Locks[callbackInfo["nukiId"]]
        self.UpdateDoorInfo(lock, callbackInfo["state"], callbackInfo["batteryChargeState"], False)
        self.UpdateSensorInfo(lock, callbackInfo["doorsensorState"], False)


    def UpdateDoorInfo(self, lock, newDoorState, newDoorbatteryChargeState, force):
        if newDoorState < 0:
            newDoorState = lock["State"]
        else:
            lock["State"] = newDoorState

        if newDoorbatteryChargeState < 0:
            newDoorbatteryChargeState = lock["Battery"]
        else:
            lock["Battery"] = newDoorbatteryChargeState

        state = min(90, newDoorState * 10)
        if force or state != lock["dzStatus"].nValue or newDoorbatteryChargeState != lock["dzStatus"].BatteryLevel:
            Domoticz.Debug("Lock status changed from")
            lock["dzStatus"].Update(nValue=state, sValue=str(state), BatteryLevel=newDoorbatteryChargeState)


    def UpdateSensorInfo(self, lock, newSensorState, force):
        if newSensorState < 0:
            newSensorState = lock["DoorSensor"]
        else:
            lock["DoorSensor"] = newSensorState

        sensor = min(70, newSensorState * 10)
        if force or sensor != lock["dzSensor"].nValue:
            Domoticz.Log("door sensor changed")
            lock["dzSensor"].Update(nValue=sensor, sValue=str(sensor))


    def DoCommand(self, nukiId, unit, command):
        if nukiId not in self.Locks:
            Domoticz.Error("Command from unknown lock")
            return

        if unit == 2:
            Domoticz.Log("Try to set a read only device")
            self.UpdateSensorInfo(self.Locks[nukiId], -1, True)
            return


        lockAction = 2
        doorState = 1
        if command == 10 or command == 40:
            lockAction = 2
            doorState = 1
        elif command == 20 or command == 30:
            lockAction = 1
            doorState = 3
        elif command == 50 or command == 70:
            lockAction = 3
            doorState = 5
        elif command == 60:
            lockAction = 4
            doorState = 6
        else:
            self.UpdateDoorInfo(self.Locks[nukiId], -1, -1, True)
            return

        bridge = self.Locks[nukiId]["Bridge"]
        self.SendDoorCommand(bridge, nukiId, lockAction)
        self.UpdateDoorInfo(self.Locks[nukiId], doorState, -1, True)


    def SendDoorCommand(self, bridge, nukiId, lockAction):
        url = 'http://' + bridge["Ip"] + ':' + bridge["Port"] + "/lockAction?token=" + bridge["ApiKey"] + "&nowait=1&nukiId=" + str(nukiId) + "&action=" + str(lockAction)
        data = urllib.request.urlopen(url).read().decode('utf-8')        
        response = json.loads(data)


    def CreateIfNotExists(self, lockInfo):
        if lockInfo["nukiId"] in self.Locks:
            return
        
        self.Locks[lockInfo["nukiId"]] = { "Name":lockInfo["name"], "DoorSensor":255, "State":255, "Battery":255}
        lock = self.Locks[lockInfo["nukiId"]]
        found = False
        for deviceId in Devices: 
            device = Devices[deviceId]
            if device.DeviceID == str(lockInfo["nukiId"]):
                found = True
                if device.Unit == 1:
                    lock["dzStatus"] = device
                if device.Unit == 2:
                    lock["dzSensor"] = device
                #if device.Unit == 3:
                #    lock["dzAction"] = device
                #if device.Unit == 4:
                #    lock["dzKeypad"] = device

        if found:
            return

        newSwitch = {}
        newSwitch['Type'] = 244
        newSwitch['Subtype'] = 62
        newSwitch['Switchtype'] = 18
        newSwitch['DeviceID'] = str(lockInfo["nukiId"])

        if "dzStatus" not in lock:
            newSwitch['Name'] = lockInfo["name"]
            newSwitch['Unit'] = 1
            newSwitch['Options'] = {"LevelActions": "|||||", "LevelNames": "uncalibrated|locked|unlocking|unlocked|locking|unlatched|unlocked (lock ‘n’ go)|unlatching|motor blocked|Unknown", "LevelOffHidden": "true", "SelectorStyle": "1"}
            Domoticz.Device(**newSwitch).Create()
            lock["dzStatus"] = Devices[len(Devices)]


        if "dzSensor" not in lock:
            newSwitch['Name'] = lockInfo["name"] + " Sensor"
            newSwitch['Unit'] = 2
            newSwitch['Options'] = {"LevelActions": "|||||", "LevelNames": "-|deactivated|door closed|door opened|unknown|calibrating|uncalibrated|removed", "LevelOffHidden": "true", "SelectorStyle": "1"}
            Domoticz.Device(**newSwitch).Create()
            lock["dzSensor"] = Devices[len(Devices)]

        #if "dzAction" not in lock:
        #    newSwitch['Name'] = lockInfo["name"] + " Action"
        #    newSwitch['Unit'] = 3
        #    newSwitch['Options'] = {"LevelActions": "|||||", "LevelNames": "-|unlock|lock|unlatch|lock ‘n’ go|lock ‘n’ go with unlatch", "LevelOffHidden": "true", "SelectorStyle": "1"}
        #    Domoticz.Device(**newSwitch).Create()
        #    lock["dzAction"] = Devices[-1]

        #if "dzKeypad" not in lock:
        #    newSwitch['Name'] = lockInfo["name"] + " Keypad"
        #    newSwitch['Unit'] = 4
        #    newSwitch['Options'] = {"LevelActions": "|||||", "LevelNames": "-|deactivated|door closed|door opened|unknown|calibrating|uncalibrated|removed", "LevelOffHidden": "true", "SelectorStyle": "1"}
        #    Domoticz.Device(**newSwitch).Create()
        #    lock["dzKeypad"] = Devices[-1]


    def CreateCallbacks(self):
        self.ListenSocket = Domoticz.Connection(Name="Nuki Callback Listeren", Transport="TCP/IP", Protocol="HTTP", Port=str(self.ListenPort))
        self.ListenSocket.Listen()
        for row in self.Bridges:
            bridge = self.Bridges[row]
            self.RegisterCallbackAtBridge(bridge)
            

    def RegisterCallbackAtBridge(self, bridge):
        myIP = self.GetLocalIp(bridge)
        callbackUrl = "http://" + str(myIP) + ":" + str(self.ListenPort)
        url = 'http://' + bridge["Ip"] + ':' + bridge["Port"] + "/callback/list?token=" + bridge["ApiKey"]
        data = urllib.request.urlopen(url).read().decode('utf-8')
        response = json.loads(data)
        if "callbacks" in response:
            for key in response["callbacks"]:                
                url = key["url"]
                if url == callbackUrl:
                    return

        url = 'http://' + bridge["Ip"] + ':' + bridge["Port"] + "/callback/add?token=" + bridge["ApiKey"] + "&url=" + callbackUrl
        data = urllib.request.urlopen(url).read().decode('utf-8')


    def GetLocalIp(self, bridge):
        probeSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probeSocket.connect((bridge["Ip"], int(bridge["Port"])))
        myIP = probeSocket.getsockname()[0]
        probeSocket.close()
        return myIP


    def SetLogLevel(self):
        loglevel = Parameters["Mode6"]
        if loglevel == "Off":
            Domoticz.Debugging(0)
            Domoticz.Trace(False)
        elif loglevel == "Debug":
            Domoticz.Debugging(1)
            Domoticz.Trace(True)
        else:
            Domoticz.Debugging(6)
            Domoticz.Trace(False)


global _plugin
_plugin = NukiPlugin()


def onStart():
    global _plugin
    _plugin.onStart()


def onMessage(Connection, data):
    global _plugin
    callbackInfo = json.loads(data["Data"].decode('utf-8'))
    _plugin.ProcessCallbackInfo(callbackInfo)


def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.DoCommand(int(Devices[Unit].DeviceID), Devices[Unit].Unit, Level)
