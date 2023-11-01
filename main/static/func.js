function showLoader(){document.getElementById("loader").style.display="unset"}function hideLoader(){document.getElementById("loader").style.display="none"}function resetClick(){updateSetting("reset_bcbox",1),setTimeout(function(){hideLoader()},60)}function mqttClientIdSaveClick(){updateSetting("mqtt_client_id",document.getElementById("MQTT_CLIENT_ID").value)}function relaysSaveClick(){updateSetting("relays",document.getElementById("RELAYS").value)}function mqttTopicClick(){updateSetting("mqtt_topic",document.getElementById("MQTT_TOPIC").value)}function apnClick(){updateSetting("apn",document.getElementById("APN").value)}function timeZoneClick(){updateSetting("time_zone",document.getElementById("TIME_ZONE").value)}function saveWifiClick(){updateWifi(document.getElementById("wifiSELECT").value,document.getElementById("wifiPWD").value)}function automaticUpdateChanged(e){let t=1;!1===e.checked&&(t=0),updateSetting("automatic_update",t)}function testingSoftwareChanged(e){let t=1;!1===e.checked&&(t=0),updateSetting("testing_software",t)}function updateWifi(e,t){showLoader(),fetch("/updateWifi",{method:"POST",body:JSON.stringify({ssid:e,password:t})}).then(()=>{hideLoader(),loadWifi(),document.getElementById("wifiPWD").value=""}).catch(e=>{console.error(e),alert(e),hideLoader()})}function updateSetting(e,t){showLoader(),fetch("/updateSetting",{method:"POST",body:JSON.stringify({variable:e,value:t})}).then(()=>{hideLoader()}).catch(e=>{console.error(e),alert(e),hideLoader()})}function loadWifi(){showLoader(),fetch("/loadWifiSSID").then(e=>e.json()).then(e=>{console.log("wifi: "+JSON.stringify(e)),document.getElementById("SSID").innerHTML=e.connectSSID;let t=document.getElementById("wifiSELECT");for(let n in t.innerHTML="",e){var i=document.createElement("option");i.value=n,i.innerHTML=n,t.appendChild(i)}hideLoader()}).catch(e=>{console.error(e),alert(e),hideLoader()})}function loadSettings(){showLoader(),fetch("/loadSettings").then(e=>e.json()).then(e=>{console.log("settings: "+JSON.stringify(e)),document.getElementById("ACTUAL_SW_VERSION").innerHTML=e.actual_sw_version,document.getElementById("WIFI_STATUS").innerHTML=e.wifi_status,document.getElementById("SUPPLY_STATUS").innerHTML=e.supply_status,document.getElementById("BATTERY_STATUS").innerHTML=e.battery_status,document.getElementById("GSM_STATUS").innerHTML=e.gsm_status,document.getElementById("GSM_SIGNAL").innerHTML=e.gsm_signal,document.getElementById("RESET_COUNTER").innerHTML=e.reset_counter,document.getElementById("ERRORS").innerHTML=e.errors,document.getElementById("ID").innerHTML=e.id,document.getElementById("AUTOMATIC_UPDATE").checked="1"===e.automatic_update,document.getElementById("TESTING_SOFTWARE").checked="1"===e.testing_software,document.getElementById("MQTT_CLIENT_ID").value=e.mqtt_client_id,document.getElementById("RELAYS").value=e.relays,document.getElementById("MQTT_TOPIC").value=e.mqtt_topic,document.getElementById("TIME_ZONE").value=e.time_zone,hideLoader(),loadWifi()}).catch(e=>{console.error(e),alert(e),hideLoader()})}