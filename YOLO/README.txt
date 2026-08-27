instalirej dependencije za pyenv:
sudo apt update
sudo apt install -y make build-essential libssl-dev zlib1g-dev \
libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm \
libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev

install pyenv:
curl https://pyenv.run | bash

dodaj na konc ~/.bashrc ali ~/.zshrc fila da bo pyenv in your path:
pise v terminalu ko zgornjo kodo pozenes, sam tisto followej
nano ~/.bashrc

export PYENV_ROOT="$HOME/.pyenv"
[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init - bash)"
eval "$(pyenv virtualenv-init -)"

apply changes:
source ~/.bashrc 

pojdi do folderja kjer bos rabu tale venv:
cd FW_DOBOT/modularAssembly/YOLO/

instalirej tisto verzijo pythona k jo rabs in ne bo zjebala importov k jih rabs:
pyenv install 3.10
# ali:
pyenv install pypy3.10-7.3.19

naredi venv:
pyenv virtualenv 3.10 train-detector-venv
# ali:
pyenv virtualenv pypy3.10-7.3.19 train-detector-venv

aktivirej venv:
pyenv activate train-detector-venv
#ali:
pyenv local train-detector-venv

installirej kr rabs:
pip install -r requirements.txt

zazeni kodo:
python main.py





HOW TO USE:
ce na novo delas najprej instaliraj vse gor ter za dobota:
pip install pydobot pydobotplus

YOLO model tece lokalno v main.py procesu prek Roboflow `inference` paketa - ni vec dockerja/inference
 serverja. Prvi zagon rabi internet (in tvoj Roboflow api_key) da prenese in cache-ira model weights
 (~/.cache ali podobno); po tem tece lokalno tudi offline. model_id v main.py (npr "train-parts-yolo/1")
 mora ustrezat tvojemu Roboflow projektu in verziji.

api_key se NE hardcoda vec v main.py (repo je javen) - nastavis ga kot environment variable preden
 zazenes kodo:
export ROBOFLOW_API_KEY="tvoj_api_key_tukaj"
 ali pa to dodaj v ~/.bashrc da ti ni treba vsakic na novo nastavljat.

ce nisi se skalibriral robota glede na kamero - torej koordinate kamere se cez transformacijsko matriko preslikajo
 koordinate robota, potem daj:
calibration_mode: True
 pri cemer damo tisto kalibracijsko plasticno 4x4 sahovnico z kvadratki 2,5cm velikimi pod delovno povrsino kjer jo kamera vidi
spremeni v calibrate_robot.py: 
CHECKERBOARD_DIMENSIONS: na tako kot vidi kamera na notranje vogale npr 4x4 torej 3x3 so notranji:
 POMEMBNO!!! Cel checkerboard more bit v vidnim polju!!!
SQUARE_SIZE_MM: 25 ce so 2,5cm veliki kvadratki
DOBOT_CALIBRATION_Z: da se robot ne zabije v mizo - tako da to bo stevilka ko se priseska / pen dotakne sahovnice
DOBOT_HOME_X, DOBOT_HOME_Y, DOBOT_HOME_Z, DOBOT_HOME_R tudi prilagodi na neko home pozicijo
DOBOT_SAFE_Z je stevilka visine ki nam omogoca da bo robot varno sel cez vse ovire med premikanjem
DOBOT_PICK_Z_MM je visina komponente kjer jo robot pobere
se se vedno ne dela dobro / ne detektira cornerjev, potem spremeni:
SIMPLE_THRESH_VALUE = 50        # Threshold value (0-255)
SIMPLE_THRESH_MAX_VALUE = 100   # Max value assigned (usually 255)
dokler ne dela dobro. tukaj imas tudi debug slikce ki ti pomagajo pri resevenju tezav ce ne dela!

calibration_mode: False ko hocemo da uporabimo pridobljeno matriko za pretvorbo koordinat kamere v koord robota
HOMOGRAPHY_MATRIX_PATH mora pri tem kazati na pridobljeno .npy matriko 

[90.0, 175.0, -58.0, 90.0, 1, 1],  x,y,z,rot,delay,suck