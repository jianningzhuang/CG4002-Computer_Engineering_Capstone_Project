// Reference: https://www.programmingelectronics.com/debouncing-a-button-with-arduino/
#include <Arduino.h>

//--------------------------------------------------------------------------------------------
#include <IRLibSendBase.h> // First include the send base
// Now include only the protocols you wish to actually use.
// The lowest numbered protocol should be first but remainder
// can be any order.
#include <IRLib_P01_NEC.h>
#include <IRLib_P02_Sony.h>
#include <IRLibCombo.h> // After all protocols, include this
// All of the above automatically creates a universal sending
// class called "IRsend" containing only the protocols you want.
// Now declare an instance of that sender.
IRsend mySender;

const int BUZZER = 5;
const int TRIGGER = 4;

int ammoCount = 6;

// INT COMMS --------------------------------------------------------------------------------------------
#include "CRC8.h"

unsigned static long currtime_ACK = 0;
unsigned static long lasttime_ACK = 0;
int received_ACK = 0;

unsigned long currtime_G = 0;
unsigned long gunSentTime = 0;
int static shootFlag = 0;

const int BUFFER_SIZE = 20;
byte buffer[BUFFER_SIZE];

CRC8 crc;

struct handshakeData
{
  char packetType;
  char checksum;
};

struct gunData
{
  char packetType;
  int seqnum;
  int seqnum_old;
  char checksum;
};

struct gunData gun_data;
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

void sendGun()
{
  crc.restart();
  gun_data.packetType = 'G';
  Serial.write(gun_data.packetType);
  crc.add(gun_data.packetType);

  Serial.write(gun_data.seqnum);
  crc.add(gun_data.seqnum);

  Serial.write(1);
  crc.add(1);

  makePadding(16);
  gun_data.checksum = crc.getCRC();
  Serial.write(gun_data.checksum);
  Serial.flush();
}

void setup()
{
  Serial.begin(115200);

  // Buzzer setup
  pinMode(BUZZER, OUTPUT);
  digitalWrite(BUZZER, LOW);

  // Trigger setup
  pinMode(TRIGGER, INPUT_PULLUP);

  // 7 seg setup
  pinMode(A0, OUTPUT);
  pinMode(A1, OUTPUT);
  pinMode(A2, OUTPUT);
  pinMode(A3, OUTPUT);
  digitalWrite(A0, LOW);
  digitalWrite(A1, LOW);
  digitalWrite(A2, LOW);
  digitalWrite(A3, LOW);
}

void transmit()
{
  shootFlag = 0;
  for (int i = 0; i < 1; i++)
  {
    mySender.send(NEC, 0x61a0f00b, 0);
  }
  shootFlag = 1;
  //delay(100);
}

void playSound()
{
  digitalWrite(BUZZER, HIGH);
  delay(300);
  digitalWrite(BUZZER, LOW);
}

void displayAmmo(int count)
{ // byte& count
  if (count == 0)
  {
    digitalWrite(A0, LOW);
    digitalWrite(A1, LOW);
    digitalWrite(A2, LOW);
    digitalWrite(A3, LOW);
  }
  else if (count == 1)
  {
    digitalWrite(A0, HIGH);
    digitalWrite(A1, LOW);
    digitalWrite(A2, LOW);
    digitalWrite(A3, LOW);
  }
  else if (count == 2)
  {
    digitalWrite(A0, LOW);
    digitalWrite(A1, HIGH);
    digitalWrite(A2, LOW);
    digitalWrite(A3, LOW);
  }
  else if (count == 3)
  {
    digitalWrite(A0, HIGH);
    digitalWrite(A1, HIGH);
    digitalWrite(A2, LOW);
    digitalWrite(A3, LOW);
  }
  else if (count == 4)
  {
    digitalWrite(A0, LOW);
    digitalWrite(A1, LOW);
    digitalWrite(A2, HIGH);
    digitalWrite(A3, LOW);
  }
  else if (count == 5)
  {
    digitalWrite(A0, HIGH);
    digitalWrite(A1, LOW);
    digitalWrite(A2, HIGH);
    digitalWrite(A3, LOW);
  }
  else if (count == 6)
  {
    digitalWrite(A0, LOW);
    digitalWrite(A1, HIGH);
    digitalWrite(A2, HIGH);
    digitalWrite(A3, LOW);
  }
  else
  {
    digitalWrite(A0, LOW);
    digitalWrite(A1, LOW);
    digitalWrite(A2, LOW);
    digitalWrite(A3, LOW);
  }
}

int buttonState = LOW;     // this variable tracks the state of the button, low if not pressed, high if pressed
long lastDebounceTime = 0; // the last time the output pin was toggled
long debounceDelay = 1000; // the debounce time; increase if the output flickers

void checkIREmitter()
{
  // sample the state of the button - is it pressed or not?
  displayAmmo(ammoCount);
  buttonState = digitalRead(TRIGGER);

  // filter out any noise by setting a time buffer
  if ((millis() - lastDebounceTime) > debounceDelay)
  {

    // if the button has been pressed, lets toggle the LED from "off to on" or "on to off"
    if (buttonState == LOW)
    {

      //playSound();

      transmit();
      lastDebounceTime = millis(); // set the current time
    }
  }
}

void loop()
{
  int static handshake_start = 0;
  int static handshake_finish = 0;
  byte packetType = buffer[0];
  byte p_hp = buffer[4];
  byte p_shield_health = buffer[8];
  byte p_bullets = buffer[12];

  checkIREmitter();

  // reads chars from serial port into buffer, terminates when 20 bytes has been read
  if (Serial.available() > 0)
  {
    int rlen = Serial.readBytes(buffer, BUFFER_SIZE);
  }

  if (packetType == 'R')
  {
    resetBeetle();
  }

  if (handshake_finish == 1)
  {

    // receive laptop ACKs to Gun packet
    if (packetType == 'A')
    {
      received_ACK = 1;
      gun_data.seqnum = gun_data.seqnum_old + 1;
    }
    if (packetType == 'U')
    {
      ammoCount = int(p_bullets);
    }

    // send if laptop has ACKed previously sent packet & Gun has been fired off
    if (received_ACK && shootFlag == 1)
    {
      sendGun();
      playSound();
      gunSentTime = millis();
      received_ACK = 0;
      shootFlag = 0;
      gun_data.seqnum_old = gun_data.seqnum;
    }

    // retransmit previously sent Gun packet due to ACK timeout
    currtime_G = millis();
    if ((received_ACK == 0) && (currtime_G - gunSentTime > 500))
    {
      gun_data.seqnum = gun_data.seqnum_old;
      sendGun();
      playSound();
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

}
