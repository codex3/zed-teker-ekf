#!/usr/bin/env python

"""
    Extended Kalman filter for localization problem using Encoder odometry and visual odometry.
    
"""

import rospy
import math
from math import cos, sin
import sys
import time

import rospkg

import numpy as np


#from sensor_msgs.msg import Imu
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Quaternion
from geometry_msgs.msg import Twist

from tf.transformations import quaternion_from_euler, rotation_matrix, quaternion_from_matrix, euler_from_quaternion
from tf.broadcaster import TransformBroadcaster
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue



# get an instance of RosPack with the default search paths
rospack = rospkg.RosPack()
# get the file path for sensor_fusion
rospack.get_path('zed_teker_ekf')

path=rospack.get_path('zed_teker_ekf')+'/dataTxt/'

ekfpos = open(path+'pos.txt', 'w')
odometer = open(path+'teker.txt', 'w')
zed = open(path+'zed.txt', 'w')

global ekfpos

class ZED_EKF(object):
	""" The state variables are x, y, theta, v, w and the sensor measurements are cameras x, y theta, v, w. """

	def __init__(self):
		
		rospy.init_node('kalman_filter')

		self.xlist = []
		self.ylist = []

		
		# starting state
		self.x = 0
		self.y = 0
		self.theta = 0 

		self.mu = np.array([self.x, self.y, self.theta, 0, 0])

		#noise in estimate state 
		self.PPred = np.array([[0.1, 0, 0, 0, 0],
								[0, 0.1, 0, 0, 0],
								[0, 0, 0.1, 0, 0],
								[0, 0, 0, 0.1, 0],
								[0, 0, 0, 0, 0.1]])      

		#Initializing initial odom/imu values
		self.zed_x = 0
		self.zed_y = 0
		self.zed_v = 0
		self.zed_w = 0

		self.z_t = np.array([self.zed_x, self.zed_y, self.zed_v, self.zed_w]) 

		# covariance matrix of process noise
		self.Q = np.diag([1, 1, 1, 1, 1])**2

#		self.Q = np.eye(5)**2
		# sensor noise
		# self.R = rospy.get_param('~R', .1)
#		self.R = np.array([[0.1, 0, 0], 
#									[0, 0.3, 0], 
#									[0, 0, 0.02]]) 
 
		self.R = np.array([[0.01, 0, 0, 0], #noise in zed_x
									[0, 0.01, 0, 0], #noise in zed_y
									[0, 0, 0.01, 0], #noise in zed_v
									[0, 0, 0, 0.01]]) #noise in zed_w

		self.H = np.array([[1, 0, 0, 0, 0],
							[0, 1, 0, 0,0],
							[0, 0, 0, 1, 0],
							[0, 0, 0, 0, 1]])

		# Publishing to topic ekf_fusion
		self.odom_pub = rospy.Publisher('ekf_fusion', Odometry, queue_size=1)
		self.odomBroadcaster = TransformBroadcaster()

		# Subscribe to Odom and IMU
#		self.imu_sub = rospy.Subscriber('imu_data', Imu, self.imu_callback)
		self.odom_sub = rospy.Subscriber('zed/odom', Odometry, self.zed_callback)
		self.teker_odom = rospy.Subscriber('odom', Odometry, self.odom_callback)


#	def imu_callback(self,msg):
		
#		self.w_imu = msg.angular_velocity.z

	def zed_callback(self,msg):

		self.zed_x = msg.pose.pose.position.x
		self.zed_y = msg.pose.pose.position.y

		zed.write("{:.9f} {:.9f}\n".format(self.zed_x, self.zed_y))

		self.zed_w = msg.twist.twist.angular.z
		self.zed_v = msg.twist.twist.linear.x
		


	def odom_callback(self,msg):
		

		self.x_odom = msg.pose.pose.position.x
		self.y_odom = msg.pose.pose.position.y

		(roll, pitch, yaw) = euler_from_quaternion([msg.pose.pose.orientation.x, msg.pose.pose.orientation.y, msg.pose.pose.orientation.z, msg.pose.pose.orientation.w])

		odometer.write("{:.9f} {:.9f}\n".format(self.x_odom, self.y_odom))


		self.w_odom = msg.twist.twist.angular.z
		self.v_odom = msg.twist.twist.linear.x 

		self.mu = np.array([self.x_odom, self.y_odom, yaw, self.v_odom, self.w_odom])
		# print "V_ODOM: " + str(self.v_odom)

	def run(self):

		r = rospy.Rate(10)
		curr_time = rospy.Time.now()
		last_time = curr_time
		odom = Odometry()
		while not rospy.is_shutdown():
			# Do Kalman updates
			curr_time = rospy.Time.now()
			dt = (curr_time - last_time).to_sec()
			last_time = curr_time

			x_k, y_k, theta_k, v_k, w_k = self.mu

			self.z_t = np.array([self.zed_x, self.zed_y, self.zed_v, self.zed_w]) 
			#Predict step
			self.mu = np.array([x_k + v_k*dt*cos(theta_k), 
								y_k + v_k*dt*sin(theta_k),
								theta_k + w_k*dt,
								v_k,
								w_k])
			#The Jacobian of update model
			F_k = np.array([[1, 0, -v_k*dt*sin(theta_k), dt*cos(theta_k), 0],
							[0, 1, -v_k*dt*cos(theta_k), dt*sin(theta_k), 0],
							[0, 0, 1, 0, dt],
							[0, 0, 0, 1, 0],
							[0, 0, 0, 0, 1]])
			#update error in prediction
			self.PPred = F_k.dot(self.PPred).dot(F_k.T) + self.Q

			#Update step
			zPred = self.H.dot(self.mu)

			measurement_residual = self.z_t - zPred

			residual_covariance = self.H.dot(self.PPred).dot(self.H.T) + self.R

			K_t = self.PPred.dot(self.H.T).dot(np.linalg.inv(residual_covariance)) #Kalman gain

			self.mu = self.mu + K_t.dot(measurement_residual)

			self.PPred = (np.eye(len(self.mu))-K_t.dot(self.H)).dot(self.PPred)

			#Publish the new odom message based on the integrated odom values
			odom.header.stamp = curr_time
			odom.pose.pose.position.x = self.mu[0]
			odom.pose.pose.position.y = self.mu[1]
			odom.pose.pose.position.z = 0


			qt_array = quaternion_from_euler(0,0,self.mu[2])
			quaternion = Quaternion(x=qt_array[0], y=qt_array[1], z=qt_array[2], w=qt_array[3])
			
			odom.pose.pose.orientation = quaternion

			odom.pose.covariance = [self.PPred[0,0], 0, 0, 0, 0, 0, 
									0, self.PPred[1,1], 0, 0, 0, 0, 
									0, 0, 0, 0, 0, 0, 
									0, 0, 0, 0, 0, 0, 
									0, 0, 0, 0, 0, 0, 
									0, 0, 0, 0, 0, self.PPred[2,2]] 

			odom.twist.twist.linear.x = self.mu[3]
			odom.twist.twist.angular.z = self.mu[4] 

			odom.twist.covariance = [self.PPred[3,3], 0, 0, 0, 0, 0,
									0, 0, 0, 0, 0, 0, 
									0, 0, 0, 0, 0, 0, 
									0, 0, 0, 0, 0, 0, 
									0, 0, 0, 0, 0, 0, 
									0, 0, 0, 0, 0, self.PPred[4,4]] 

			self.odomBroadcaster.sendTransform((self.mu[0], self.mu[1], 0), (quaternion.x, quaternion.y, quaternion.z, quaternion.w), curr_time, "base_link", "ekf_fusion" )
			self.odom_pub.publish(odom)


			ekfpos.write("{:.9f} {:.9f}\n".format(self.mu[0], self.mu[1]))

			try:
				r.sleep()
			except rospy.exceptions.ROSTimeMovedBackwardsException:
				print "Time went backwards. Carry on."	


		
if __name__ == '__main__':
	node = ZED_EKF()
	node.run()
