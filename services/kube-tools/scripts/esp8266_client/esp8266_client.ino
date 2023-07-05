#include <Arduino_JSON.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecureBearSSL.h>
#include <Adafruit_Sensor.h>
#include <DHT.h>

typedef struct SensorData
{
  float temperature;
  float humidity;
};

ADC_MODE(ADC_VCC);

#define DHTPIN 5      // Digital pin connected to the DHT sensor
#define DHTTYPE DHT22 // DHT 22 (AM2302)

const unsigned long period = 5000;
const char *ssid = "";
const char *password = "";
const char *deviceId = "f0a719fa-0dc7-4842-bd25-2a0c4f76677f";
const char *apiKey = "50384447-cc4c-485b-84fb-7057591fcea2";
const char *device_key = "bedroom-temp-monitor";
const char *base_url = "https://api.dan-leonard.com/";
const char *url = "https://api.dan-leonard.com/api/tools/nest/sensor";

uint32_t heap_free;
uint16_t heap_max;
uint8_t heap_frag;

unsigned long currentMillis;
unsigned long startMillis;
unsigned long cycles = 0;

String json_body = String("");

SensorData captured;

DHT dht(DHTPIN, DHTTYPE);
WiFiClient wifiClient;
HTTPClient httpClient;

void print(String message)
{
  Serial.println(message);
  Serial.println("");
}

void get_sensor_data()
{
  captured.temperature = dht.readTemperature();
  captured.humidity = dht.readHumidity();
}

void build_json_payload(String &rtn)
{
  JSONVar payload;
  JSONVar diag;

  payload["degrees_celsius"] = captured.temperature;
  payload["humidity_percent"] = captured.humidity;
  payload["sensor_id"] = deviceId;

  ESP.getHeapStats(&heap_free, &heap_max, &heap_frag);

  diag["vcc"] = (int)ESP.getVcc();
  diag["rsr"] = (String)ESP.getResetReason();
  diag["mil"] = (int)millis();
  diag["cyc"] = (int)cycles;

  JSONVar heap;

  heap["free"] = (int)heap_free;
  heap["max"] = (int)heap_max;
  heap["frag"] = (float)heap_frag;

  diag["heap"] = heap;
  payload["diagnostics"] = diag;

  rtn = JSON.stringify(payload);
}

void connect_wifi()
{
  Serial.print("Connecting to: ");
  Serial.println(ssid);

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED)
  {
    delay(1000);
    Serial.print(".");
  }
}

void post_json(String endpoint, String json)
{
  // Allow insecure requests (workaround for HTTPS)
  wifiClient.setInsecure();

  // Configure the request (content type, key auth)
  httpClient.begin(client, endpoint);
  httpClient.addHeader("Content-Type", "application/json");
  httpClient.addHeader("X-Api-Key", "50384447-cc4c-485b-84fb-7057591fcea2");

  // POST sensor data to the service endpoint
  // and get the response as a string
  int statusCode = httpClient.POST(json);
  String response = httpClient.getString();

  Serial.println("Response: ");
  Serial.print(response);
  Serial.println("");

  Serial.println("Status code: ");
  Serial.print(statusCode);
  Serial.println("");

  httpClient.end();
}

void post_sensor_data()
{
  print("Posting sensor data");

  get_sensor_data();

  // Capture DHT22 sensor data (temp and humidity)
  // and create the request payload as a JSON string
  build_json_payload(
      json_body);

  // POST the sensor data to service endpoint
  post_json(url, json_body);
}

void setup()
{
  Serial.begin(115200);
  dht.begin();

  connect_wifi();

  Serial.println("Connected: ");
  Serial.println(WiFi.localIP());

  startMillis = millis();
}

void loop()
{
  post_sensor_data();

  delay(3000);
  cycles++;
}
