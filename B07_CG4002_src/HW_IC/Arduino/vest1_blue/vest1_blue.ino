#include <Arduino.h>

//----------------------------------IR-----------------------------------
#include <IRLibDecodeBase.h>
#include <IRLibSendBase.h>
#include <IRLib_P01_NEC.h>
#include <IRLibCombo.h>
//#include <IRLibRecv.h>
//#include <IRLibRecvLoop.h>
#include <IRLibRecvPCI.h>
#include <IRLibFreq.h>
const int IR_PIN = 2;
IRrecvPCI myReceiver(IR_PIN); // pin number for the receiver
IRdecode myDecoder;
uint16_t myBuffer[RECV_BUF_LENGTH];
//-----------------------------------------------------------------------

//----------------------------------Health---------------------------------
#include <FastLED.h>
int health = 100;
const int HEALTH_PIN = 4;
const int lednum = 5;
CRGB leds[lednum];
//-----------------------------------------------------------------------

//-------------------------------Shield--------------------------------------
const int SHIELD_LED = 3;
int shield_health = 0;
//------------------------------------------------------------------------

// INT COMMS --------------------------------------------------------------------------------------------
#include "CRC8.h"

unsigned static long currtime_ACK = 0;
unsigned static long lasttime_ACK = 0;
int received_ACK = 0;

unsigned long currtime_V = 0;
unsigned long vestSentTime = 0;
int static hitFlag = 0;

const int BUFFER_SIZE = 20;
byte buffer[BUFFER_SIZE];

CRC8 crc;

struct handshakeData
{
  char packetType;
  char checksum;
};

struct vestData
{
  char packetType;
  int seqnum;
  int seqnum_old;
  char checksum;
};

struct vestData vest_data;
struct handshakeData handshake_data;

void (*resetBeetle)(void) = 0;

void makePadding(int n)
{
  for (int i = 0; i < n; i++)
  {
    Serial.write('0');
    crc.add('0');
  }
}

void sendACK()
{
  crc.restart();
  handshake_data.packetType = 'A';
  Serial.write(handshake_data.packetType);
  crc.add(handshake_data.packetType);
  makePadding(18);
  handshake_data.checksum = crc.getCRC();
  Serial.write(handshake_data.checksum);
  Serial.flush();
}

void sendVest()
{
  crc.restart();
  vest_data.packetType = 'V';
  Serial.write(vest_data.packetType);
  crc.add(vest_data.packetType);

  Serial.write(vest_data.seqnum);
  crc.add(vest_data.seqnum);

  Serial.write(1);
  crc.add(1);

  makePadding(16);
  vest_data.checksum = crc.getCRC();
  Serial.write(vest_data.checksum);
  Serial.flush();
}

void checkIRReceiver()
{
  hitFlag = 0;

  if (myReceiver.getResults())
  {
    myDecoder.decode();
    if (myDecoder.value == 1637937163)
    { // vest1: 1637937163 vest2:1637937162
      hitFlag = 1;
      //digitalWrite(SHIELD_LED, HIGH);
      myReceiver.enableIRIn();
      delay(100);
      //digitalWrite(SHIELD_LED, LOW);
    }
    myReceiver.enableIRIn();
  }
  else
  {
    delay(100);
  }

  if ((shield_health) > 0) {
    digitalWrite(SHIELD_LED, HIGH);        
  } else {
    digitalWrite(SHIELD_LED, LOW);
  }

  if (health == 100)
  {
    leds[0] = CRGB(255, 0, 0);
    leds[1] = CRGB(255, 0, 0);
    leds[2] = CRGB(255, 0, 0);
    leds[3] = CRGB(255, 0, 0);
    leds[4] = CRGB(255, 0, 0);
    FastLED.show();
  }
  else if (health == 90)
  {
    leds[0] = CRGB(255, 0, 0);
    leds[1] = CRGB(255, 0, 0);
    leds[2] = CRGB(255, 0, 0);
    leds[3] = CRGB(255, 0, 0);
    leds[4] = CRGB(0, 0, 0);
    FastLED.show();
  }
  else if (health == 80)
  {
    leds[0] = CRGB(255, 0, 0);
    leds[1] = CRGB(255, 0, 0);
    leds[2] = CRGB(255, 0, 0);
    leds[3] = CRGB(0, 0, 0);
    leds[4] = CRGB(0, 0, 0);
    FastLED.show();
  }
  else if (health == 70)
  {
    leds[0] = CRGB(255, 0, 0);
    leds[1] = CRGB(255, 0, 0);
    leds[2] = CRGB(0, 0, 0);
    leds[3] = CRGB(0, 0, 0);
    leds[4] = CRGB(0, 0, 0);
    FastLED.show();
  }
  else if (health == 60)
  {
    leds[0] = CRGB(255, 0, 0);
    leds[1] = CRGB(0, 0, 0);
    leds[2] = CRGB(0, 0, 0);
    leds[3] = CRGB(0, 0, 0);
    leds[4] = CRGB(0, 0, 0);
    FastLED.show();
  }
  else if (health == 50)
  {
    leds[0] = CRGB(0, 0, 255);
    leds[1] = CRGB(0, 0, 255);
    leds[2] = CRGB(0, 0, 255);
    leds[3] = CRGB(0, 0, 255);
    leds[4] = CRGB(0, 0, 255);
    FastLED.show();
  }
  else if (health == 40)
  {
    leds[0] = CRGB(0, 0, 255);
    leds[1] = CRGB(0, 0, 255);
    leds[2] = CRGB(0, 0, 255);
    leds[3] = CRGB(0, 0, 255);
    leds[4] = CRGB(0, 0, 0);
    FastLED.show();
  }
  else if (health == 30)
  {
    leds[0] = CRGB(0, 0, 255);
    leds[1] = CRGB(0, 0, 255);
    leds[2] = CRGB(0, 0, 255);
    leds[3] = CRGB(0, 0, 0);
    leds[4] = CRGB(0, 0, 0);
    FastLED.show();
  }
  else if (health == 20)
  {
    leds[0] = CRGB(0, 0, 255);
    leds[1] = CRGB(0, 0, 255);
    leds[2] = CRGB(0, 0, 0);
    leds[3] = CRGB(0, 0, 0);
    leds[4] = CRGB(0, 0, 0);
    FastLED.show();
  }
  else if (health == 10)
  {
    leds[0] = CRGB(0, 0, 255);
    leds[1] = CRGB(0, 0, 0);
    leds[2] = CRGB(0, 0, 0);
    leds[3] = CRGB(0, 0, 0);
    leds[4] = CRGB(0, 0, 0);
    FastLED.show();
  }
  else if (health == 0)
  {
    leds[0] = CRGB(0, 0, 0);
    leds[1] = CRGB(0, 0, 0);
    leds[2] = CRGB(0, 0, 0);
    leds[3] = CRGB(0, 0, 0);
    leds[4] = CRGB(0, 0, 0);
    FastLED.show();
  }
}

void setup()
{
  Serial.begin(115200);
  myReceiver.enableAutoResume(myBuffer);
  myReceiver.enableIRIn(); // Start the receiver

  FastLED.addLeds<WS2812, HEALTH_PIN, GRB>(leds, lednum);
  FastLED.setBrightness(2);

  pinMode(SHIELD_LED, OUTPUT);
  digitalWrite(SHIELD_LED, LOW);
}

void loop()
{
  int static handshake_start = 0;
  int static handshake_finish = 0;
  byte packetType = buffer[0];
  byte p_hp = buffer[8];
  byte p_shield_health = buffer[4];

  checkIRReceiver();

  // reads chars from serial port into buffer, terminates when 20 bytes has been read
  if (Serial.available() > 0)
  {
    int rlen = Serial.readBytes(buffer, BUFFER_SIZE);
  }

  /*if (packetType == 'R')
  {
    resetBeetle();
  }*/

  if (handshake_finish == 1)
  {
      //checkIRReceiver();

    // receive laptop ACKs to Vest packet
    if (packetType == 'A')
    {
      received_ACK = 1;
      vest_data.seqnum = vest_data.seqnum_old + 1;
    }

    if (packetType == 'U')
    {
      health = int(p_hp);
      shield_health = int(p_shield_health);
    }

    // send if laptop has ACKed previously sent packet & Gun has been fired off
    if (received_ACK && hitFlag == 1)
    {
      sendVest();
      vestSentTime = millis();
      received_ACK = 0;
      hitFlag = 0;
      vest_data.seqnum_old = vest_data.seqnum;
    }

    // retransmit previously sent Gun packet due to ACK timeout
    currtime_V = millis();
    if ((received_ACK == 0) && (currtime_V - vestSentTime > 500))
    {
      vest_data.seqnum = vest_data.seqnum_old;
      sendVest();
    }
  }

  if (packetType == 'H')
  {
    currtime_ACK = millis();
    if (currtime_ACK - lasttime_ACK > 350)
    {
      sendACK();
      handshake_start = 1;
      handshake_finish = 0;
      lasttime_ACK = currtime_ACK;
    }
  }
  if (packetType == 'A' && handshake_start == 1)
  {
    received_ACK = 1;
    handshake_start = 0;
    handshake_finish = 1;
  }
  
  hitFlag = 0;
  
}
