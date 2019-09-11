配合compute_ha实现计算节点的高可用
==========

## 1. 背景

如我们所知，计算节点高可用的数据采集和收集功能扩展自ceilometer，而正常情况下如果云产品已经集成具备一般功能的ceilometer，所以如果对计算节点高可用功能有需求，需要对原先的ceilometer进行升级（安装）操作。

## 2. Ceilometer升级

其实升级就是我们通过新package把ceilometer重新装一遍，具体过程下文将一一展开说明。

### 准备安装包

下载ceilometer安装包，假设安装包名称：`ceilometer_6.2.0-1~u14.04+mos38~1.gbp6d1af1.zip`，通过md5sum保存安装包的MD5码（以便我们在把安装包拷贝到生产/测试环境之后确认安装包是否OK），而安装包里具体的文件组成大致会如下图所示：
* ceilometer安装包构成

![](https://upload-images.jianshu.io/upload_images/12911861-d13d3ac3e51dec2e.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/550)

### 配置文件备份

在升级之前，建议把每个控制节点和计算节点上的ceilometer的配置文件拷贝一份以作备份：
```bash
cp -fr /etc/ceilometer/ /etc/ceilometer_bak/
```

### 升级部署

ceilometer在控制节点和计算节点上各自的功能和角色不一样，所以他们的升级部署会略有不同，下面分两块一一说明。

#### 控制节点升级部署

##### 安装

首先，可以通过执行`dpkg -l | grep -i ceilometer-`和`dpkg -l | grep -i python-ceilometer`来查看控制节点原始安装的ceilometer相关的包，然后进行一一升级。
* 控制节点需要安装的ceilometer的包：

![](https://upload-images.jianshu.io/upload_images/12911861-6bf6e5988d6b7fb7.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/550)

其中上图中最底部`python-ceilometerclient`不需要再重新安装了，剩下的7个由于依赖关系，我们需要先安装`python-ceilometer`，然后安装`ceilometer-common`，之后5个不用考虑顺序依次完成安装即可。

##### 配置文件

我们知道一般ceilometer收集数据的的后端采用的是`gnocchi`，而为了使用不同的数据库，独立于`ceilometer-collector`服务新增`ceilometer-collector-ha`服务，如此就需要新增该服务的启动文件和配置文件。

###### 启动文件

```bash
# 拷贝/etc/init/ceilometer-collector.conf做更改，具体的样式可参照下图(只列出更改部分)
cp /etc/init/ceilometer-collector.conf /etc/init/ceilometer-collector-ha.conf
```
* 截图如下

![](https://upload-images.jianshu.io/upload_images/12911861-1f46c9ba3ae123eb.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/550)

另外，如果考虑到后续程序要被CRM管理实现该可用，开机启动也应该被禁掉。

###### 服务配置文件

从上图`ceilometer-collector-ha`的启动文件不难看出，这个新增的服务会有自己的配置文件`ceilometer_ha.conf`，这个文件是从`ceilometer.conf`拷贝而来然后再进行编辑，具体的样式可如下：
```bash
[DEFAULT]
# Polling namespace(s) to be used while resource polling (list value)
# Allowed values: compute, central, ipmi
polling_namespaces = central

# Dispatchers to process metering data. (multi valued)
# Deprecated group/name - [DEFAULT]/dispatcher
meter_dispatchers = database

# If set to true, the logging level will be set to DEBUG instead of the default INFO level. (boolean value)
debug = false

# If set to false, the logging level will be set to WARNING instead of the default INFO level. (boolean value)
# This option is deprecated for removal.
# Its value may be silently ignored in the future.
verbose = true

[collector]
# Address to which the UDP socket is bound. Set to an empty string to disable. (string value)
udp_address = 0.0.0.0

# Port to which the UDP socket is bound. (port value)
# Minimum value: 0
# Maximum value: 65535
udp_port = 4953

[database]
# Number of seconds that samples are kept in the database for (<= 0 means forever). (integer value)
# Deprecated group/name - [database]/time_to_live
metering_time_to_live = 1800

# The SQLAlchemy connection string to use to connect to the database. (string value)
# Deprecated group/name - [DEFAULT]/sql_connection
# Deprecated group/name - [DATABASE]/sql_connection
# Deprecated group/name - [sql]/connection
connection = mysql://ceilometer:ceilometer123@192.168.0.2/ceilometer?charset=utf8

[publisher]
# Secret value for signing messages. Set value empty if signing is not required to avoid computational overhead. (string value)
# Deprecated group/name - [DEFAULT]/metering_secret
# Deprecated group/name - [publisher_rpc]/metering_secret
# Deprecated group/name - [publisher]/metering_secret
telemetry_secret = nmWpu7Pu8DDWhQ3oPaBpVQjn
```

##### 服务启动

```bash
service ceilometer-collector-ha start
```

#### 计算节点升级部署

##### 安装

跟在控制节点安装的过程类似，具体要安装的包如下图所示，至于一些安装过程中需要注意的细节可参照控制节点的上安装说明。
* 要安装的包

![](https://upload-images.jianshu.io/upload_images/12911861-3c4c7cbf06b5afac.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/550)

##### 配置文件

我们知道，ceilometer计算节点上的服务是用来采集数据的，为防止其他数据采集异常影响计算节点高可用服务程序的判断，独立于`ceilometer-polling`服务新增`ceilometer-polling-ha`服务，如此就需要新增该服务的启动文件和配置文件。

###### 启动文件

upstart管理的服务启动文件跟在控制节点处理类似，此处就不再赘述。

###### 服务配置文件

这一块可能需要我们稍微注意一下，首先需要处理的配置文件有三个：`/etc/ceilometer/{ceilometer_ha.conf, pipeline.yaml, pipeline_ha.yaml}`，如下会分别给出这三个文件的样式供参考。

* /etc/ceilometer/pipeline.yaml

![](https://upload-images.jianshu.io/upload_images/12911861-e97f64b87c9b2323.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/550)

* /etc/ceilometer/ceilometer_ha.conf
```bash
[DEAFULT]
# Polling namespace(s) to be used while resource polling (list value)
# Allowed values: compute, central, ipmi
polling_namespaces = compute

# List of metadata keys reserved for metering use. And these keys are additional to the ones included in the namespace. (list value)
reserved_metadata_keys = cluster

# Configuration file for pipeline definition. (string value)
pipeline_cfg_file = pipeline_ha.yaml

# If set to true, the logging level will be set to DEBUG instead of the default INFO level. (boolean value)
debug = false

# If set to false, the logging level will be set to WARNING instead of the default INFO level. (boolean value)
# This option is deprecated for removal.
# Its value may be silently ignored in the future.
verbose = true

# Log output to standard error. This option is ignored if log_config_append is set. (boolean value)
use_stderr = false

# The messaging driver to use, defaults to rabbit. Other drivers include amqp and zmq. (string value)
# rpc_backend = rabbit

[compute]
# Some storage address used to check storage-connectivity. (string value)
storage_server_address = 192.168.0.10, 192.168.0.20

# Count of ping storage gateway. (integer value)
ping_count = 4

# Ping loss ratio that can be accepted. (floating point value)
ping_loss_ratio = 0.5

[keystone_authtoken]
# Complete public Identity API endpoint. (string value)
auth_uri = http://192.168.0.2:5000/v2.0

[publisher]
# Secret value for signing messages. Set value empty if signing is not required to avoid computational overhead. (string value)
# Deprecated group/name - [DEFAULT]/metering_secret
# Deprecated group/name - [publisher_rpc]/metering_secret
# Deprecated group/name - [publisher]/metering_secret
telemetry_secret = nmWpu7Pu8DDWhQ3oPaBpVQjn

[service_credentials]
# Region name to use for OpenStack service endpoints. (string value)
# Deprecated group/name - [DEFAULT]/os_region_name
region_name = RegionOne

# Type of endpoint in Identity service catalog to use for communication with OpenStack services. (string value)
# Allowed values: public, internal, admin, auth, publicURL, internalURL, adminURL
# Deprecated group/name - [DEFAULT]/os_endpoint_type
interface = internalURL

# Authentication URL (unknown value)
auth_url = http://192.168.0.2:5000/v2.0/

# Project name to scope to (unknown value)
# Deprecated group/name - [DEFAULT]/tenant-name
project_name = services

# Username (unknown value)
# Deprecated group/name - [DEFAULT]/user-name
username = ceilometer

# User's password (unknown value)
password = a1b2c3d4e5
```

* /etc/ceilometer/pipeline_ha.conf

![](https://upload-images.jianshu.io/upload_images/12911861-1f9b32fac1494bd8.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/550)

#### 服务启动
```bash
service ceilometer-polling-ha start
```

另：以上的安装过程在所有的控制节点和计算节点上均需操作。

## 3. 一些畅想

很显然如果是人工来完成上述的安装升级操作，这一套流程还是很复杂的且费时，所以建议将其集成到FUEL或者其他自动化部署Openstack集群的的工具当中；另外控制节点上收集数据的服务及UMHA服务可以通过CRM管理也做个高可用，如此计算节点高可用功能体验或许会更好。

