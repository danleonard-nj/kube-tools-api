#include <Arduino_JSON.h>
#include <ESP8266WiFi.h>
#include <ESP8266WiFiMulti.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecureBearSSL.h>

char* ssid     = "HotGiblets24";
char* password = "vN55]8T7D7`+/W42I=BP:56CMXJ6$]w2";
char* deviceId = "41651552-6c5c-4465-b5ed-4cd32d17772e";
char* apiKey = "50384447-cc4c-485b-84fb-7057591fcea2";
char* device_key = "bedroom-temp-monitor";
char* base_url = "https://api.dan-leonard.com";

int interval = 1000;
const char* host = "djxmmx.net";
const uint16_t port = 17;

ESP8266WiFiMulti wifiMulti;
WiFiClient wifiClient;
HTTPClient httpClient;
  
String build_json_payload(int degreesCelsius, char* deviceId) {
  JSONVar payload;

  payload["degrees_celsius"] = degreesCelsius;
  payload["sensor_id"] = deviceId;

  String jsonString = JSON.stringify(payload);
  Serial.println(jsonString);

  return jsonString;
}

void connect_wifi() {
  Serial.print("Connecting to: ");
  Serial.println(ssid);


  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.print(".");
  }
}

void post_sensor_data(int degreesCelsius, char* deviceId) {
  HTTPClient https;
  WiFiClientSecure client;

  client.setInsecure();
  
  Serial.println("Posting sensor data");
  
  String url = String(base_url) + String("/api/tools/nest/sensor");
  Serial.println("Endpoint: ");
  Serial.print(url);
  Serial.println("");

  String json = build_json_payload(degreesCelsius, deviceId);

  https.begin(client, url);
  https.addHeader("Content-Type", "application/json");
  https.addHeader("X-Api-Key", "50384447-cc4c-485b-84fb-7057591fcea2");

  int statusCode = https.POST(json);

  String response = https.getString();
  Serial.println("Response:");
  Serial.println(response);
  
  https.end();

  Serial.println("Status code: ");
  Serial.print(statusCode);
}

void setup() {
  Serial.begin(115200);

  connect_wifi();

  Serial.println("Connected: ");
  Serial.println(WiFi.localIP());
}

void loop() {
  post_sensor_data(0, deviceId);
  delay(interval);
}
