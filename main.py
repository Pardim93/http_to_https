import os

path = '/home/wellington/Documents/fretebras/fretebras-site'

files = []
# r=root, d=directories, f = files
for r, d, f in os.walk(path):
    for file in f:
        if '.php' in file:
            files.append(os.path.join(r, file))
print(len(files))

# for f in files:
#     print(f)