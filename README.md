A fully autonomous, professional-grade real-time seismograph system, developed from scratch. The system features a scalable backend for seismic data acquisition and processing, along with an interactive frontend for real-time monitoring and advanced visualization.

📡 Seismic Station 
The seismic node is built on a Raspberry Pi running Python, integrated with:
NEO-6M GPS module for precise time synchronization

SM24 high-sensitivity geophone

ADS1115 16-bit ADC

Achieving a 250 Hz sampling rate for accurate waveform capture and tremor detection

The station is fully autonomous, with automatic error recovery and self-restart mechanisms to ensure high availability and resilience in the field.

🔗 Real-Time Data Pipeline
Communication via WebSocket between seismic station, backend server, and clients

Backend hosted on Hetzner, running Python services behind an NGINX reverse proxy

Incoming data is filtered and processed, then relayed to a web-based client

The frontend, built in React, is optimized for clarity, performance, and near-zero latency, offering:

Live waveform plotting

Real-time spectrogram visualization

🧑🏻‍💻Current Deployment & Scalability
The station is currently operating in test mode in downtown Athens, an environment with high ambient vibration, so live tremors should not be interpreted as seismic events

The system is designed for multi-node synchronization, with incoming data stored in MongoDB

Expansion is planned across Greece, forming a real-time seismic monitoring network
