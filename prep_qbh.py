#-*- coding:utf-8 -*-   #允许文档中有中文
"""
预处理DBN训练数据与标签，转换为满足DBN输入要求的格式

功能包括：
1.对训练数据预处理，有三种处理方法：
(1)unit：归一化，均值为0
(2)normalize：规范化，均值为0，方差为1
(3)student：规范化，均值为0，方差为1，计算方差时均值采用 x.sum()/(N-ddof)
2.将标签转换为0-(clus_cnt-1)内的类号，clus_cnt为类数
3.按比例将训练数据划分为训练集，验证集，测试集

"""

import theano, copy, sys, json, cPickle
import theano.tensor as T
import numpy as np

BORROW = True   # True makes it faster with the GPU
                #设置共享变量时的参数，为true能在GPU上运行更快
USE_CACHING = False # beware if you use RBM / GRBM or gammatones / speaker labels alternatively, set it to False
                    #为true时使用预先处理的训练数据和标签文件，而不对其进行预处理，直接划分训练集，验证集，测试集
DTYPE = 'float64'   #训练数据类型

def prep_data(dataset, scaling='normalize'):    #预处理训练数据，scaling为处理方法
                                                #预处理标签，转换为0-(clus_cnt-1)内的类号，clus_cnt为类数
                                                #将类号和类名的映射存储到文件to_int_and_to_state_dicts_tuple中
    xname = "xdata"
    try:
        train_x = np.load(dataset + "/train_xdata.npy")
        train_y = np.load(dataset + "/train_ylabels_kmeans.npy")

    except:
        print >> sys.stderr, "you need the .npy python arrays"
        print >> sys.stderr, "you can produce them with txt_to_numpy.py"
        print >> sys.stderr, dataset + "/train_xdata.npy"
        print >> sys.stderr, dataset + "/train_ylabels_kmeans.npy"
        sys.exit(-1)

    print "train_x shape:", train_x.shape

    if scaling == 'unit':
        ### Putting values on [0-1]
        train_x = (train_x - np.min(train_x, 0)) / np.max(train_x, 0)
    elif scaling == 'normalize':
        ### Normalizing (0 mean, 1 variance)
        # TODO or do that globally on all data (but that would mean to know
        # the test set and this is cheating!)
        train_x = (train_x - np.mean(train_x, 0)) / np.std(train_x, 0)
    elif scaling == 'student':
        ### T-statistic
        train_x = (train_x - np.mean(train_x, 0)) / np.std(train_x, ddof=1)
    train_x_f = train_x

    ### Labels (Ys)
    from collections import Counter
    c = Counter(train_y)    #统计train_y的每个值的个数，即每个分类的类名和属于该分类的样本数
    to_int = dict([(k, c.keys().index(k)) for k in c.iterkeys()])   #to_int记录{类名,类序号}map
    to_state = dict([(c.keys().index(k), k) for k in c.iterkeys()]) #to_state记录{类序号，类名}map
    # print to_int
    # print to_state
    with open(dataset+'/to_int_and_to_state_dicts_tuple.pickle', 'w') as f:
        cPickle.dump((to_int, to_state), f)

    print "preparing / int mapping Ys"
    train_y_f = np.zeros(train_y.shape[0], dtype='float64')
    for i, e in enumerate(train_y):
        train_y_f[i] = to_int[e]    #记录每个样本对应的类号
        # print train_y_f[i]

    return [train_x_f, train_y_f]


def load_data(dataset, scaling='normalize',
        valid_cv_frac=0.2, test_cv_frac=0.2,
        numpy_array_only=False):        #预处理训练数据和标签，用prep_data处理后按比例划分训练集，验证集，测试集

    """ 
    params:
     - dataset: folder
                数据所在文件夹

     - scaling: 'none' || 'unit' (put all the data into [0-1])
                || 'normalize' ((X-mean(X))/std(X))
                || student ((X-mean(X))/std(X, deg_of_liberty=1))
                处理训练数据方法
                (1)unit：归一化，均值为0
                (2)normalize：规范化，均值为0，方差为1
                (3)student：规范化，均值为0，方差为1，计算方差时均值采用 x.sum()/(N-ddof)

     - valid_cv_frac: valid cross validation fraction on the train set
                验证集在训练数据中占的比例

     - test_cv_frac: test cross validation fraction on the train set
                测试集在训练数据中占的比例
     - numpy_array_only: true when only use numpy arrays; false when use shared arrays
                为false时将训练集，验证集，测试集设置为共享变量

    """

    params = {'scaling': scaling,
              'valid_cv_frac': valid_cv_frac,
              'test_cv_frac': test_cv_frac,
              'theano_borrow?': BORROW,
              'use_caching?': USE_CACHING}
    # with open('prep_' + '_params.json', 'w') as f:
    #     f.write(json.dumps(params))


    def prep_and_serialize():
        [train_x, train_y] = prep_data(dataset, scaling=scaling,
                pca_whiten=pca_whiten)
        with open(dataset+'/train_x_' + scaling + '.npy', 'w') as f:
            np.save(f, train_x)
        with open(dataset+'/train_y_' + scaling + '.npy', 'w') as f:
            np.save(f, train_y)
        print ">>> Serialized all train/test tables"
        return [train_x, train_y]

    if USE_CACHING:     #是否使用预先处理好的文件
        try: # try to load from serialized filed, beware
            with open(dataset+'/train_x_' + scaling + '.npy') as f:
                train_x = np.load(f)
            with open(dataset+'/train_y_' + scaling + '.npy') as f:
                train_y = np.load(f)
        except: # do the whole preparation (normalization / padding)
            [train_x, train_y] = prep_and_serialize()
    else:
        [train_x, train_y] = prep_and_serialize()

    #划分数据集，验证集，测试集
    from sklearn import cross_validation
    X_train1, X_validate, y_train1, y_validate = cross_validation.train_test_split(train_x, train_y, test_size=valid_cv_frac, random_state=0)
    real_test_cv_frac = test_cv_frac / (1.0 - valid_cv_frac)
    X_train, test_x, y_train, test_y = cross_validation.train_test_split(X_train1, y_train1, test_size=real_test_cv_frac, random_state=0)
    
    #生成最终数据，设置共享变量
    if numpy_array_only:
        train_set_x = X_train
        train_set_y = np.asarray(y_train, dtype=DTYPE)
        val_set_x = X_validate
        val_set_y = np.asarray(y_validate, dtype=DTYPE)
        test_set_x = test_x
        test_set_y = np.asarray(test_y, dtype=DTYPE)
    else:
        train_set_x = theano.shared(X_train, borrow=BORROW)
        train_set_y = theano.shared(np.asarray(y_train, dtype=theano.config.floatX), borrow=BORROW)
        train_set_y = T.cast(train_set_y, DTYPE)
        val_set_x = theano.shared(X_validate, borrow=BORROW)
        val_set_y = theano.shared(np.asarray(y_validate, dtype=theano.config.floatX), borrow=BORROW)
        val_set_y = T.cast(val_set_y, DTYPE)
        test_set_x = theano.shared(test_x, borrow=BORROW)
        test_set_y = theano.shared(np.asarray(test_y, dtype=theano.config.floatX), borrow=BORROW)
        test_set_y = T.cast(test_set_y, DTYPE)

    return [(train_set_x, train_set_y), 
            (val_set_x, val_set_y),
            (test_set_x, test_set_y)] 
