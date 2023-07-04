#include "CRC8.h"
#include "I2Cdev.h"
#include "MPU6050.h"
// Arduino Wire library is required if I2Cdev I2CDEV_ARDUINO_WIRE implementation
// is used in I2Cdev.h
#if I2CDEV_IMPLEMENTATION == I2CDEV_ARDUINO_WIRE
    #include "Wire.h"
#endif

// class default I2C address is 0x68
// specific I2C addresses may be passed as a parameter here
// AD0 low = 0x68 (default for InvenSense evaluation board)
// AD0 high = 0x69
MPU6050 accelgyro;
//MPU6050 accelgyro(0x69); // <-- use for AD0 high
//MPU6050 accelgyro(0x68, &Wire1); // <-- use for AD0 low, but 2nd Wire (TWI/I2C) object

struct acc {
  float acc_x;
  float acc_y;
  float acc_z;
};

struct acc currentAcc;

struct gyro {
  float gyro_x;
  float gyro_y;
  float gyro_z;
};

struct gyro currentGyro;

int16_t ax, ay, az;
int16_t gx, gy, gz;

// thresholding vars
float acc_x_avg, acc_y_avg, acc_z_avg;
float acc_x_avg_prev = -20000, acc_y_avg_prev = -20000, acc_z_avg_prev = -20000;

// 25hz
const int send_size = 40;
const int frame_size = 6;
// 50hz
//const int send_size = 80;
//const int frame_size = 10;
const int threshold = 4;
bool send = false;
int counter = 0;
acc accs[frame_size];
float avg_checks[3];
//int sent_counter = 0;
//acc prev = { .acc_x = 0, .acc_y = 0, .acc_z = 0 };
//acc curr;

// ================================================================
// ===                         THRESHOLDING                     ===
// ================================================================

void addMotionDataToMovements(int index) {
  accs[index] = currentAcc;
}

void checkThreshold() {
  acc_x_avg = 0;
  acc_y_avg = 0;
  acc_z_avg = 0;
  for (int i = 0; i < frame_size; i++)
  {
    acc_x_avg += accs[i].acc_x;
    acc_y_avg += accs[i].acc_y;
    acc_z_avg += accs[i].acc_z;
  }

  acc_x_avg /= frame_size;
  acc_y_avg /= frame_size;
  acc_z_avg /= frame_size;

  if (acc_x_avg_prev != -20000)
  {
    avg_checks[0] = abs(acc_x_avg - acc_x_avg_prev) > threshold;
    avg_checks[1] = abs(acc_y_avg - acc_y_avg_prev) > threshold;
    avg_checks[2] = abs(acc_z_avg - acc_z_avg_prev) > threshold;

    int sum_check = 0;
    for (int i = 0; i < 3; i++)
    {
      sum_check += avg_checks[i];
    }
    // If more than one avg exceeds threshold, start of move
    if (sum_check >= 1) {
      send = true;
    }
  }

  if (send == true) {
    acc_x_avg_prev = -20000;
    acc_y_avg_prev = -20000;
    acc_z_avg_prev = -20000;    
  } else {
    acc_x_avg_prev = acc_x_avg;
    acc_y_avg_prev = acc_y_avg;
    acc_z_avg_prev = acc_z_avg;
  }
}

// ================================================================
// ===                      INITIAL SETUP                       ===
// ================================================================

void setup() {
    // join I2C bus (I2Cdev library doesn't do this automatically)
    #if I2CDEV_IMPLEMENTATION == I2CDEV_ARDUINO_WIRE
        Wire.begin();
    #elif I2CDEV_IMPLEMENTATION == I2CDEV_BUILTIN_FASTWIRE
        Fastwire::setup(400, true);
    #endif
    
    Serial.begin(115200);
    accelgyro.initialize();
    accelgyro.setFullScaleGyroRange(1);
    accelgyro.setFullScaleAccelRange(2);    
    accelgyro.setDLPFMode(4);
    accelgyro.setXAccelOffset(-4552);
    accelgyro.setYAccelOffset(1400);
    accelgyro.setZAccelOffset(1422);
    accelgyro.setXGyroOffset(95);
    accelgyro.setYGyroOffset(-27);
    accelgyro.setZGyroOffset(-87);
}

void readMotionData() {
  accelgyro.getMotion6(&ax, &ay, &az, &gx, &gy, &gz);
  currentAcc.acc_x = (ax * 0.002395); // 32767) * 9.81 * 8;
  currentAcc.acc_y = (ay * 0.002395); // 32767) * 9.81 * 8;
  currentAcc.acc_z = (az * 0.002395); // 32767) * 9.81 * 8;
  currentGyro.gyro_x = (gx * 0.01526); // 32767) * 500;
  currentGyro.gyro_y = (gy * 0.01526); // 32767) * 500;
  currentGyro.gyro_z = (gz * 0.01526); // 32767) * 500;

}

// ================================================================
// ===                   BLUETOOTH FUNCTIONS                    ===
// ================================================================

CRC8 crc;

struct handshakeData {
  int8_t packetType;
  int8_t checksum;
};

struct motionData {
  int8_t packetType;
  int16_t  roll;
  int16_t  pitch;
  int16_t  yaw;
  int8_t checksum;
};

unsigned static long currtime_ACK = 0;
unsigned static long lasttime_ACK = 0;
int static initFlag = 0;
const int BUFFER_SIZE = 20;
byte buffer[BUFFER_SIZE];
unsigned long previousMillis = 0;

struct motionData motion_data;
struct handshakeData handshake_data;
byte twoByteBuf[2];

void (* resetBeetle) (void) = 0;

void makePadding(int n) {
  for (int i = 0; i < n; i++) {
    Serial.write('0');
    crc.add('0');
  }
}

void writeIntToSerial(int16_t data) {
  twoByteBuf[1] = data & 255;
  twoByteBuf[0] = (data >> 8) & 255;
  Serial.write(twoByteBuf, sizeof(twoByteBuf));
  crc.add(twoByteBuf, sizeof(twoByteBuf));
}


void sendACK() {
  crc.restart();
  handshake_data.packetType = 'A';
  Serial.write(handshake_data.packetType);
  crc.add(handshake_data.packetType);
  makePadding(18);
  handshake_data.checksum = crc.getCRC();
  Serial.write(handshake_data.checksum);
  Serial.flush();
}

void sendMotionData() {
  crc.restart();
  motion_data.packetType = 'M';
  Serial.write(motion_data.packetType);
  crc.add(motion_data.packetType);

  //readMotionData();
  writeIntToSerial(int16_t(currentAcc.acc_x * 100));
  writeIntToSerial(int16_t(currentAcc.acc_y * 100));
  writeIntToSerial(int16_t(currentAcc.acc_z * 100));
  writeIntToSerial(int16_t(currentGyro.gyro_x * 100));
  writeIntToSerial(int16_t(currentGyro.gyro_y * 100));
  writeIntToSerial(int16_t(currentGyro.gyro_z * 100));

  makePadding(6);
  motion_data.checksum = crc.getCRC();
  Serial.write(motion_data.checksum);
  Serial.flush();
}

void sendIndicator() {
  crc.restart();
  motion_data.packetType = 'M';
  Serial.write(motion_data.packetType);
  crc.add(motion_data.packetType);

  //readMotionData();
  writeIntToSerial(int16_t(200 * 100));
  writeIntToSerial(int16_t(200 * 100));
  writeIntToSerial(int16_t(200 * 100));
  writeIntToSerial(int16_t(200 * 100));
  writeIntToSerial(int16_t(200 * 100));
  writeIntToSerial(int16_t(200 * 100));

  makePadding(6);
  motion_data.checksum = crc.getCRC();
  Serial.write(motion_data.checksum);
  Serial.flush();
}
// ================================================================
// ===                    MAIN PROGRAM LOOP                     ===
// ================================================================

void loop() {
  int static handshake_start = 0;
  int static handshake_finish = 0;
  byte packetType = buffer[0];


  //reads chars from serial port into buffer, terminates when 20 bytes has been read
  if (Serial.available() > 0) {
    int rlen = Serial.readBytes(buffer, BUFFER_SIZE);
  }

  /*if (packetType == 'R') {
    resetBeetle();
  }*/

  if (packetType == 'H') {
    currtime_ACK = millis();
    if(currtime_ACK-lasttime_ACK>350){
      sendACK();
      handshake_start = 1;
      handshake_finish = 0;
      lasttime_ACK = currtime_ACK;
    }
  }

  if (packetType == 'A' && handshake_start == 1) {
    handshake_start = 0;
    handshake_finish = 1;
  }
  /*send = true;
  if (send == true) {
      //if (counter == 0){
      //  sendIndicator();
      //}

      readMotionData();
      Serial.print(currentAcc.acc_x);
      Serial.print(',');
      Serial.print(currentAcc.acc_y);
      Serial.print(',');
      Serial.print(currentAcc.acc_z);
      Serial.print(',');
      Serial.print(currentGyro.gyro_x);
      Serial.print(',');
      Serial.print(currentGyro.gyro_y);
      Serial.print(',');
      Serial.println(currentGyro.gyro_z);
      //sendMotionData();
      //addMotionDataToMovements(counter);
      //addMotionDataToSendBuff(counter);
      //Serial.print("Sending");
      //if (counter == (send_size - 1)) {
      //  sendIndicator();
      //}

      counter += 1;
      if (counter >= send_size) {
        counter = 0;
        send = false;
        checkThreshold();
      }
    } else {
      readMotionData();
      addMotionDataToMovements(counter);
      counter += 1;      
      if (counter >= frame_size) {
        counter = 0;
        checkThreshold();        
      }
      
    }*/

  unsigned long currentMillis = millis();
  if (handshake_finish == 1 && currentMillis - previousMillis >= 40) {
    previousMillis = currentMillis;
    
    if (send == true) {
      if (counter == 0){
        sendIndicator();
        sendIndicator();
        sendIndicator();
        sendIndicator();
        sendIndicator();
      }

      readMotionData();
      sendMotionData();
      //addMotionDataToMovements(counter);
      //addMotionDataToSendBuff(counter);
      //Serial.print("Sending");
      if (counter == (send_size - 1)) {
        sendIndicator();
        sendIndicator();
        sendIndicator();
        sendIndicator();
        sendIndicator();
      }

      counter += 1;
      if (counter >= send_size) {
        counter = 0;
        send = false;
        checkThreshold();
      }
    } else {
      readMotionData();
      addMotionDataToMovements(counter);
      counter += 1;      
      if (counter >= frame_size) {
        counter = 0;
        checkThreshold();        
      }
      
    }
  }  
}
