# Compound Calculator (standalone)

A **standalone** compound interest app for your computer.  
Not part of any crypto/scanner project. No website. No browser link.

## What it does

- Principal
- Daily rate (%)
- Monthly rate (%)
- Number of months
- Final balance + **every-day breakdown**

Each month = 30 daily compounds, then one monthly compound.

## Run on computer

```bash
cd compound-calculator
pip install -r requirements.txt
python calculator.py
```

A normal app window opens (not a browser tab).

### Windows

```bat
pip install -r requirements.txt
python calculator.py
```

### Mac / Linux

```bash
pip3 install -r requirements.txt
python3 calculator.py
```

## Run on phone

1. Install **Pydroid 3** (Android) from the Play Store  
2. Copy `calculator.py` onto your phone  
3. In Pydroid: `pip install flet` then open and run `calculator.py`

Or use any Python app runner that supports Flet.

## Share with anyone

Zip this whole `compound-calculator` folder and send it.  
They install Python + run the two commands above. No account, no website.
