import os, sys, mmap

def modify_file(filepath):

    with open(filepath, 'r+') as file, \
        mmap.mmap(file.fileno(), 0) as mm:
                
        http_to_https = mm.read().replace(b'http:', b'https:')
        
        print(http_to_https)
        
        mm.resize(len(http_to_https))             
        mm.seek(0)
        mm.write(http_to_https)
        
        mm.flush()
        mm.close()

def get_filepaths():    

    project_path = get_project_path()
    file_exts = get_files_extensions()

    # array to store filepaths with matched extensions
    filepaths = []
    # walk over the entire project looking for the extensions
    for root, directories, files in os.walk(project_path):
        for file in files:
            #  get file extension
            file_ext = os.path.splitext(file)[-1]
            if file_ext in file_exts:
                filepaths.append(os.path.join(root, file))
    # print(filepaths)
    modify_file(filepaths[0])

def get_files_extensions():
    exts = input("Enter the file extensions you want to modify separated by " \
                             "commas:\n")
    
    # remove trailing and leading space
    exts = list(map(str.strip, exts.split(',')))  
    # add dots if needed 
    exts = [ ext if ext[0] == '.' else '.' + ext for ext in exts ]

    return exts

def get_project_path():
    project_path = input("Enter the absoulte project path or hit enter to use your current directory:\n")

    # user entered enter, then get cwd
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
        get_filepaths()

main()
