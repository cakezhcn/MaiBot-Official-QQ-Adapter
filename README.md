# MaiBot Official QQ Adapter

This project is an official QQ adapter for the MaiBot framework.

## Installation

To install the necessary dependencies, run:

```bash
pip install -r requirements.txt
```

## Configuration

Configuration files should be structured as indicated in `config/config_example.toml`.

## Usage

To start the adapter manager, run:

```bash
python main.py
```

## File Structure:
- `main.py`: Entry point for the adapter manager.
- `adapter/qq_adapter.py`: QQ official bot adapter implementation.
- `server/webhook_server.py`: Webhook handling.
- `adapter/message_converter.py`: Message format conversion.
- `config/config_example.toml`: Configuration template.
- `requirements.txt`: Project dependencies.
