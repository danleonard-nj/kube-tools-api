#include <Arduino_JSON.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecureBearSSL.h>
#include <Adafruit_Sensor.h>
#include <DHT.h>

#define DHTPIN 5     // Digital pin connected to the DHT sensor
#define DHTTYPE    DHT22     // DHT 22 (AM2302)

char* ssid     = "HotGiblets24";
char* password = "vN55]8T7D7`+/W42I=BP:56CMXJ6$]w2";
//char* deviceId = "41651552-6c5c-4465-b5ed-4cd32d17772e";
char* deviceId = "3974a713-174a-471e-a86f-e850ce97d937";
char* apiKey = "50384447-cc4c-485b-84fb-7057591fcea2";
char* device_key = "bedroom-temp-monitor";
char* base_url = "https://api.dan-leonard.com";

DHT dht(DHTPIN, DHTTYPE);
WiFiClient wifiClient;
HTTPClient httpClient;

struct SensorData {
  float temperature;
  float humidity;
};

void print(String message) {
  Serial.println(message);
  Serial.println("");
}

SensorData get_sensor_data() {
  SensorData data;

  data.temperature = dht.readTemperature();
  data.humidity = dht.readHumidity();

  return data;
}
  
String build_json_payload(SensorData data, char* deviceId) {
  JSONVar payload;

  print("Building JSON payload");

  payload["degrees_celsius"] = data.temperature;
  payload["humidity_percent"] = data.humidity;
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

void post_json(String endpoint, String json) {
  HTTPClient https;
  WiFiClientSecure client;

  // Allow insecure requests (workaround for HTTPS)
  client.setInsecure();

  // Configure the request (content type, key auth)
  https.begin(client, endpoint);
  https.addHeader("Content-Type", "application/json");
  https.addHeader("X-Api-Key", "50384447-cc4c-485b-84fb-7057591fcea2");

  // POST sensor data to the service endpoint
  // and get the response as a string
  int statusCode = https.POST(json);
  String response = https.getString();
  
  Serial.println("Response: ");
  Serial.print(response);
  Serial.println("");
  
  https.end();

  Serial.println("Status code: ");
  Serial.print(statusCode);
  Serial.println("");
}

void post_sensor_data() {
  print("Posting sensor data");

  // Sensor data request endpoint
  String url = String(base_url) + String("/api/tools/nest/sensor");
  print(url);

  // Capture DHT22 sensor data (temp and humidity)
  // and create the request payload as a JSON string
  String json = build_json_payload(
    get_sensor_data(),
    deviceId);

  // POST the sensor data to service endpoint
  post_json(url, json);
}

void setup() {
  Serial.begin(115200);
  dht.begin();

  connect_wifi();

  Serial.println("Connected: ");
  Serial.println(WiFi.localIP());
}

void loop() {
  post_sensor_data();
  delay(1000);
}
