# SimilarWeb Data Extract to CSV

This script lets you extract data from the SimlarWeb API and export the results to a CSV file. The input is a CSV file that contains domain names

## Getting Started

<!-- These instructions will get you a copy of the project up and running on your local machine for development and testing purposes. See deployment for notes on how to deploy the project on a live system. -->


### Prerequisites

To start working on this project, make sure you have python>3.9 installed with pip (preferably in a virtual environment) and run the command

Linux / Mac OS
```
pip install -r requirements.txt
```

Windows
```
pip install -r requirements-win.txt
```

### Build executable

To build an executable file from this script you can use pyinstaller:

```
pyinstaller --clean main.spec
```

It will generate a binary file for the OS you're currently running, and save it in the *dist* folder.


## Author

* **Lior Friedman** - *Initial work* - [email](gregory.fryns@similarweb.com)

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details
