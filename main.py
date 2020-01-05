import os, sys
# path = '/home/wellington/Documents/fretebras/fretebras-site'
def get_files():    

    project_path = get_project_path()
    file_extensions = get_files_extensions()
    files = []
    # r=root, d=directories, f = files
    for r, d, f in os.walk(project_path):
        for file in f:
            if '.php' in file:
                files.append(os.path.join(r, file))
    return files

def get_files_extensions():
    file_extensions = input("Enter the file extensions you want to modify separated by " \
                             "commas:\n")

    file_extensions = file_extensions.split(',')
    print(file_extensions)

def get_project_path():
    project_path = input("Enter the absoulte project path or hit enter to use your current directory:\n")

    # user entered enter then get cwd
    if not project_path:
        project_path = os.getcwd()

    if not os.path.isdir(project_path):
        print("Entered path doesn't exist. Aborting...")
        sys.exit(0)
    
    print("Path entered: " + project_path)
    
    return project_path
def main():
    # check if it's being executed directly
    if __name__ == "__main__":
        get_files()

main()
